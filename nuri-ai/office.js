// GH Nano 사무실: 앱에 연결된 AI 모델과 스킬로 만든 자유 대화형 에이전트 팀
// - 팀·방·직원은 코드로 정해 두고, 누가 어떤 순서로 말할지도 코드가 정한다(AI는 말만 한다).
//   흐름: 담당 분석가 → (투자·실행 판단이면) 전략가 → 반론 검토관 → 리스크 책임자 → 팀장 정리
// - 사용자가 아무것도 치지 않아도 정해진 안건과 급변동 감시로 스스로 회의를 연다(자동 회의).
import { settings, saveSettings, idb, uid, brainStream, splitThink, overCap, provUse, LAUNCHER } from "./engine.js";
import { runAgent, activeSkills, TOOLS, marketNews, candlesFor, visibleText, snapText, toModelMessages } from "./agent.js";
import { fusionSources, TRAIN_SYS } from "./train.js";

/* ============ 팀과 직원 ============ */
export const TEAMS = [
  {id: "hq", name: "CEO실", desc: "CEO · 비서실 · 전사 회의 소집과 시간별 성과 발표"},
  {id: "coin", name: "코인팀", desc: "현물 · 선물·파생 · 온체인·고래 · 알트코인 · 코인 뉴스"},
  {id: "stock", name: "글로벌주식팀", desc: "미국 테크 · 국내주식 · 가치·배당 · 실적·공시 · ETF·섹터"},
  {id: "fut", name: "매크로·선물팀", desc: "해외선물·원자재 · 국내선물 · 금리·채권 · 환율 · 경제지표 예측"},
  {id: "realestate", name: "부동산팀", desc: "재개발·재건축 발굴 · 입지·상권 · 경매·공매 · 정책·세금 · 부동산 지표 개발"},
  {id: "arch", name: "건축팀", desc: "설계 · 3D·렌더링 · 구조·견적 · 인테리어 · BIM·친환경"},
  {id: "quant", name: "퀀트 연구소", desc: "매매법 개발 · 백테스트 검증 · 모의투자 · 머신러닝·딥러닝 · 커스텀 지표"},
  {id: "strat", name: "전략·리스크팀", desc: "전략 총괄 · 반론 · 리스크 · 포트폴리오 · 시나리오 · 컴플라이언스"},
  {id: "data", name: "데이터·미디어팀", desc: "SNS 여론 · 유튜브 · 인스타 · 데이터 수집 · 시각화 · 컴퓨터 작업"},
  {id: "lab", name: "AI·개발팀", desc: "CTO · 리서치 · GH Nano 학습 · 터미널 개발 · MLOps · QA"},
  {id: "venture", name: "신사업팀", desc: "자체 코인(모의 발행) · 토큰 이코노미 · 스마트컨트랙트 · 코인 터미널 · 사업 전략"}
];
// look: 머리색·옷색 (픽셀 캐릭터), role: 모델 고르는 기준
export const AGENTS = [
  {id: "lead", name: "한결", team: "hq", title: "팀장", role: "general", skills: [], look: ["#2b2b3a", "#4a6cf7"],
    duty: "사용자의 질문을 받아 팀원 발언을 종합해 최종 답을 준다. 결론 → 근거(누가 무엇을 확인했는지) → 반론·리스크 → 다음에 할 일 순서로, 사용자에게 바로 쓸 수 있는 답을 쓴다."},
  {id: "coin_spot", name: "코코", team: "coin", title: "코인 현물 분석가", role: "general", skills: ["crypto_spot"], look: ["#f5c542", "#f08a24"],
    duty: "업비트·바이낸스 현물 차트(추세·지지저항·거래량·김치 프리미엄)를 실제 도구로 확인해 해석한다."},
  {id: "coin_fut", name: "레오", team: "coin", title: "코인 선물 분석가", role: "general", skills: ["crypto_futures"], look: ["#3a2a1a", "#e2483d"],
    duty: "바이낸스 무기한 선물의 펀딩비·미결제약정·롱숏비율·청산가로 과열과 쏠림을 해석한다."},
  {id: "us", name: "엠마", team: "stock", title: "해외주식 분석가", role: "general", skills: ["us_stocks"], look: ["#c46a2b", "#2e9e6a"],
    duty: "미국 주식·ETF의 차트와 실적·금리·섹터 흐름을 연결해 해석한다."},
  {id: "kr", name: "서준", team: "stock", title: "국내주식 분석가", role: "general", skills: ["kr_stocks"], look: ["#1f1f1f", "#3c7dd9"],
    duty: "코스피·코스닥 종목의 차트와 외국인·기관 수급, 업종 흐름, 환율 영향을 해석한다."},
  {id: "gfut", name: "올리버", team: "fut", title: "해외선물 분석가", role: "general", skills: ["global_futures"], look: ["#8a5a2b", "#5a5f73"],
    duty: "원유·금·지수 선물·국채 선물의 수급 요인과 만기·증거금 같은 선물 특성을 해석한다."},
  {id: "kfut", name: "지우", team: "fut", title: "국내선물 분석가", role: "general", skills: ["kr_futures"], look: ["#2a1d14", "#9a4fd6"],
    duty: "코스피200 선물·미니 선물·야간선물을 기초지수, 외국인 선물 수급, 베이시스, 만기일과 연결해 해석한다."},
  {id: "macro", name: "노바", team: "fut", title: "거시경제·뉴스 분석가", role: "general", skills: ["macro", "news"], look: ["#d9d9d9", "#1aa3a3"],
    duty: "경제 일정(금리·물가·고용)과 최신 뉴스를 찾아 시장에 주는 영향을 말로 해설한다. 기사 제목을 나열하지 않는다."},
  {id: "arch", name: "하린", team: "arch", title: "건축 설계사", role: "general", skills: ["arch"], look: ["#5b3a29", "#e7a33c"],
    duty: "대지 조건으로 배치·층수·평면을 설계하고 공사비를 추정한다. 설계는 자유로운 설명으로 풀어 쓴다."},
  {id: "land", name: "도윤", team: "arch", title: "부동산·법규 전문가", role: "general", skills: ["land"], look: ["#222", "#6b8e23"],
    duty: "용도지역·건폐율·용적률·재개발·경매·세금 같은 부동산 제도와 위험을 설명한다."},
  {id: "strat", name: "민재", team: "strat", title: "전략가(퀀트)", role: "reason", skills: ["backtest"], look: ["#3b2f2f", "#334e9e"],
    duty: "분석가들의 의견으로 실행 계획(진입 조건·손절·목표·기간)이나 전략 초안을 만들고, 필요하면 백테스트로 확인한다."},
  {id: "devil", name: "수아", team: "strat", title: "반론 검토관", role: "reason", skills: [], look: ["#7a1f2b", "#444"],
    duty: "앞의 의견과 계획에 대한 반대 근거를 최소 3개 든다. 마지막 줄에 '판정: 동의' / '판정: 반대' / '판정: 추가 확인 필요' 중 하나만 쓴다."},
  {id: "risk", name: "태오", team: "strat", title: "리스크 책임자", role: "reason", skills: [], look: ["#111", "#b8860b"],
    duty: "손실 한도·비중·레버리지·최악의 시나리오를 숫자로 점검한다. 계획을 승인·축소·거부할 수 있지만 키우지는 않는다. 마지막 줄에 '리스크 판정: 승인' / '축소' / '거부' 중 하나를 쓴다."},
  {id: "research", name: "리아", team: "lab", title: "리서처", role: "general", skills: ["research"], look: ["#e8b04b", "#5c6bc0"],
    duty: "인터넷과 NVIDIA 스킬 문서에서 자료를 찾아 출처와 함께 정리한다."},
  {id: "dev", name: "코디", team: "lab", title: "개발자", role: "code", skills: ["coding"], look: ["#333", "#2d2d2d"],
    duty: "코드·자동화·데이터 처리 질문에 동작하는 코드와 설명을 준다."},
  {id: "aide", name: "하루", team: "lab", title: "비서(일상·글쓰기·번역)", role: "general", skills: [], look: ["#6d4c41", "#ef6c9a"],
    duty: "일상 대화, 글쓰기, 번역, 요약, 계획 세우기를 친절하게 돕는다."},
  {id: "qa", name: "준호", team: "quant", title: "퀀트 연구원(추세)", role: "reason", skills: ["backtest", "crypto_futures"], look: ["#1d1d2b", "#2f9e6b"],
    duty: "보조지표 29종(indicator_all)·호가·고래·선물 수급과 연구 카드를 보고 추세추종 매매법을 만들고, history_backtest로 가장 오래된 과거부터 모든 레버리지·장세 시나리오까지 직접 시험한다."},
  {id: "qb", name: "세라", team: "quant", title: "퀀트 연구원(역추세·변동성)", role: "reason", skills: ["backtest", "crypto_spot"], look: ["#a0522d", "#c2185b"],
    duty: "과매수·과매도, 밴드 이탈, 변동성 수축·확장, 고래 체결·호가 불균형을 노리는 매매법을 만들고 history_backtest로 전체 과거·모든 레버리지 시나리오를 시험한다."},
  {id: "val", name: "다온", team: "quant", title: "백테스트 검증관", role: "reason", skills: ["backtest"], look: ["#444", "#607d8b"],
    duty: "백테스트 결과의 과최적화 위험을 따진다(검증 구간 성과, 거래 수, 낙폭, 수수료). 코드 판정을 쉬운 말로 설명하고 통과·불통과를 뒤집지 않는다."},
  {id: "trader", name: "현우", team: "quant", title: "모의투자 트레이더", role: "general", skills: ["crypto_futures"], look: ["#2e2e2e", "#f57c00"],
    duty: "코인·주식·선물 모의투자 장부(paper_status)와 호가·고래 체결(orderbook, whale_trades)을 보고 포지션·손익과 다음 대응을 보고한다. 실제 주문은 하지 않는다."},
  {id: "sns", name: "유나", team: "data", title: "SNS·여론 분석가", role: "general", skills: ["news"], look: ["#d4a017", "#8e24aa"],
    duty: "레딧·스톡트윗·공포탐욕지수(sns_buzz)로 사람들의 분위기와 쏠림을 읽고, 뉴스와 비교해 과열·공포를 해설한다."},
  {id: "eng", name: "태민", team: "data", title: "데이터 엔지니어(컴퓨터 작업)", role: "code", skills: ["coding"], look: ["#3e2723", "#455a64"], computer: true,
    duty: "사무실 전용 폴더(문서/GHNano 사무실)에서 보고서·데이터 파일을 만들고 파이썬 스크립트를 짜서 실행한다(office_write, office_run)."}
];
// ---- 조직 개편: 분야별 팀장 1명 + 직원 5명 (해외 대기업식 직함) ----
const NEW_STAFF = [
  ["deriv", "지안", "coin", "선물·파생 애널리스트", ["crypto_futures"], ["#2b1d0e", "#ff7043"], "펀딩·미결제약정·롱숏·청산 지도와 호가·고래 흐름(futures_flow, orderbook, whale_trades)으로 쏠림을 해설한다."],
  ["onchain", "도하", "coin", "온체인·고래 애널리스트", ["crypto_spot"], ["#1b1b1b", "#00897b"], "고래 체결·대형 주문벽·거래소 흐름을 추적해 큰손의 진입·이탈을 보고한다."],
  ["alt", "윤슬", "coin", "알트코인 애널리스트", ["crypto_spot"], ["#8d6e63", "#ab47bc"], "알트코인 순위·거래대금 급증·섹터(레이어1·AI·밈) 순환을 분석한다."],
  ["coinnews", "하람", "coin", "코인 뉴스·규제 애널리스트", ["news", "crypto_spot"], ["#212121", "#26a69a"], "코인 뉴스·규제·해킹·상장 공지를 찾아 시장 영향으로 해설한다."],
  ["techus", "리나", "stock", "미국 테크 애널리스트", ["us_stocks"], ["#5d4037", "#42a5f5"], "빅테크·반도체·AI 기업의 실적·가이던스·차트를 분석한다."],
  ["value", "태하", "stock", "가치·배당 애널리스트", ["us_stocks", "kr_stocks"], ["#263238", "#8bc34a"], "밸류에이션·배당·현금흐름 관점으로 종목을 고른다."],
  ["earnings", "은호", "stock", "실적·공시 애널리스트", ["kr_stocks", "us_stocks"], ["#3e2723", "#ffb300"], "실적 발표·공시·컨센서스 서프라이즈를 추적한다."],
  ["etf", "소율", "stock", "ETF·섹터 전략가", ["us_stocks"], ["#4e342e", "#ec407a"], "섹터 순환·ETF 자금 흐름으로 지금 강한 업종을 찾는다."],
  ["rates", "해준", "fut", "금리·채권 이코노미스트", ["macro"], ["#1a237e", "#90a4ae"], "미 국채 금리·연준 기대·장단기 금리차를 해설한다."],
  ["fx", "다인", "fut", "환율 전략가", ["macro"], ["#6d4c41", "#26c6da"], "달러인덱스·원달러·엔화 흐름과 자산시장 영향을 분석한다."],
  ["econfc", "시온", "fut", "경제지표 예측 이코노미스트", ["macro"], ["#424242", "#7e57c2"], "FRED 경제지표(물가·고용·금리·성장)를 모아 다음 발표를 예측하고 맞았는지 채점한다."],
  ["redev", "은서", "realestate", "재개발·재건축 리서처", ["land"], ["#4a2c2a", "#66bb6a"], "정비구역·신속통합기획·모아타운·노후도·역세권 정보를 찾아 재개발 후보지를 발굴하고 점수를 매긴다."],
  ["location", "건우", "realestate", "입지·상권 분석가", ["land"], ["#212121", "#ffa726"], "교통·학군·일자리·개발 호재·상권으로 입지를 평가한다."],
  ["auction", "하진", "realestate", "경매·공매 전문가", ["land"], ["#5d4037", "#78909c"], "법원경매·공매 물건과 권리분석 포인트를 조사한다."],
  ["retax", "라희", "realestate", "부동산 정책·세금 전문가", ["land"], ["#3e2723", "#f06292"], "대출 규제·세금·청약·정비사업 제도 변화를 해설한다."],
  ["reind", "준서", "realestate", "부동산 지표 개발자", ["land"], ["#1c1c1c", "#9ccc65"], "재개발 잠재력·가격 모멘텀 같은 자체 부동산 지표를 만들고 실제 사례로 검증한다."],
  ["designer", "민호", "arch", "설계 디자이너", ["arch"], ["#2e2e2e", "#29b6f6"], "대지 조건으로 배치·평면·층수를 설계하고 매번 이전 안을 개선한다."],
  ["render", "채원", "arch", "3D·렌더링 아티스트", ["arch"], ["#6d4c41", "#ff8a65"], "설계안을 AI 렌더링(render_image)으로 투시도·인테리어 이미지로 만든다."],
  ["struct", "우진", "arch", "구조·견적 엔지니어", ["arch"], ["#37474f", "#bdbdbd"], "구조 방식과 공사비 견적(cost_estimate)을 검토한다."],
  ["interior", "서아", "arch", "인테리어 디자이너", ["arch"], ["#795548", "#f48fb1"], "용도에 맞는 실내 구성·마감·조명을 제안한다."],
  ["bim", "태윤", "arch", "BIM·친환경 설계가", ["arch"], ["#263238", "#4db6ac"], "에너지·일조·친환경 인증과 BIM 데이터 관점으로 설계를 다듬는다."],
  ["ml", "유진", "quant", "머신러닝·딥러닝 리서처", ["backtest"], ["#212121", "#5c6bc0"], "보조지표를 특징으로 로지스틱 회귀·신경망을 학습해 방향을 예측하고 워크포워드로 검증한다."],
  ["cind", "강민", "quant", "커스텀 지표 개발자", ["backtest"], ["#3e2723", "#ffca28"], "거래소 기본 지표가 아닌 자체 수식 지표를 만들어 전략에 넣고 시험한다."],
  ["pm", "예린", "strat", "포트폴리오 매니저", [], ["#4e342e", "#8d6e63"], "모의투자 전략들의 비중·상관·합산 낙폭을 관리한다."],
  ["scen", "정우", "strat", "시나리오 플래너", [], ["#212121", "#5e35b1"], "금리·전쟁·폭락 같은 시나리오별 영향과 대응을 준비한다."],
  ["comp", "아린", "strat", "컴플라이언스 책임자", [], ["#5d4037", "#e57373"], "법·규제·윤리 위험(투자 권유, 코인 발행 규제, 저작권)을 점검한다."],
  ["yt", "지호", "data", "유튜브 리서처", ["news"], ["#1b1b1b", "#f44336"], "유튜브에서 경제·코인·부동산 영상 흐름과 인기 주제를 찾아 요약한다."],
  ["insta", "나연", "data", "인스타·SNS 리서처", ["news"], ["#8d6e63", "#e91e63"], "인스타그램·커뮤니티에서 유행과 대중 심리를 살핀다."],
  ["crawl", "시우", "data", "데이터 수집 엔지니어", ["coding"], ["#263238", "#43a047"], "공개 데이터(FRED, 거래소, 공공데이터)를 모으고 품질을 점검한다."],
  ["viz", "보라", "data", "데이터 시각화 디자이너", [], ["#4a148c", "#ba68c8"], "결과를 표와 차트로 정리해 발표 자료를 만든다."],
  ["nano", "현서", "lab", "GH Nano 학습 엔지니어", ["coding"], ["#212121", "#00acc1"], "GH Nano 학습 데이터 품질과 학습 계획을 관리한다."],
  ["fe", "승우", "lab", "프론트엔드·터미널 개발자", ["coding"], ["#3e2723", "#7cb342"], "자체 코인 터미널과 대시보드 화면 코드를 만든다."],
  ["mlops", "다은", "lab", "MLOps 엔지니어", ["coding"], ["#5d4037", "#039be5"], "모델 학습·평가 파이프라인과 기록을 관리한다."],
  ["qae", "재윤", "lab", "QA 엔지니어", ["coding"], ["#1b1b1b", "#ff7043"], "만든 코드와 결과의 버그·오류를 찾는다."],
  ["vlead", "이안", "venture", "신사업 총괄(팀장)", [], ["#1a1a1a", "#3949ab"], "자체 코인·코인 터미널·자체 AI 같은 새 사업을 기획하고 진척을 관리한다."],
  ["token", "가은", "venture", "토큰 이코노미스트", [], ["#6d4c41", "#ffb74d"], "자체 코인의 발행량·분배·소각·유동성 설계를 시뮬레이션한다."],
  ["solidity", "준혁", "venture", "스마트컨트랙트 개발자", ["coding"], ["#212121", "#26a69a"], "ERC-20 컨트랙트와 테스트 코드를 사무실 폴더에 작성한다(실제 배포는 하지 않음)."],
  ["terminal", "소희", "venture", "코인 터미널 기획자", ["coding"], ["#4e342e", "#29b6f6"], "자체 코인 터미널(차트·호가·주문 화면) 기획서와 HTML 시제품을 만든다."],
  ["biz", "동현", "venture", "사업 전략가", [], ["#263238", "#9575cd"], "시장 규모·경쟁·수익 모델과 규제 위험을 정리한다."],
  ["brand", "미소", "venture", "브랜딩·마케팅 매니저", [], ["#8d6e63", "#f06292"], "이름·로고 콘셉트·홍보 문구를 만든다."]
];
for (const [id, name, team, title, skills, look, duty] of NEW_STAFF) AGENTS.push({id, name, team, title, role: /리서처|개발자|엔지니어/.test(title) && skills.includes("coding") ? "code" : "general", skills, look, duty});
// 기존 직원 재배치·직함
const RETITLE = {lead: ["hq", "CEO"], aide: ["hq", "비서실장"], coin_fut: ["coin", "코인팀장 · 선물"], coin_spot: ["coin", "현물 애널리스트"], us: ["stock", "글로벌주식팀장 · 미국주식"], kr: ["stock", "국내주식 애널리스트"],
  macro: ["fut", "매크로·선물팀장 · 거시경제"], gfut: ["fut", "해외선물·원자재 애널리스트"], kfut: ["fut", "국내선물 애널리스트"], land: ["realestate", "부동산팀장"], arch: ["arch", "건축팀장 · 수석 건축가"],
  qa: ["quant", "퀀트 연구소장 · 추세 전략"], qb: ["quant", "퀀트 연구원 · 역추세·변동성"], val: ["quant", "백테스트 검증관"], trader: ["quant", "모의투자 트레이더"],
  strat: ["strat", "전략 총괄(CSO)"], devil: ["strat", "반론 검토관"], risk: ["strat", "리스크 책임자(CRO)"], sns: ["data", "데이터·미디어팀장 · SNS 여론"], eng: ["data", "데이터 엔지니어(컴퓨터 작업)"],
  dev: ["lab", "CTO · AI·개발팀장"], research: ["lab", "리서치 사이언티스트"]};
for (const a of AGENTS){ const r = RETITLE[a.id]; if (r){ a.team = r[0]; a.title = r[1]; } }
export const TEAM_LEAD = {hq: "lead", coin: "coin_fut", stock: "us", fut: "macro", realestate: "land", arch: "arch", quant: "qa", strat: "strat", data: "sns", lab: "dev", venture: "vlead"};
for (const a of AGENTS) a.lead = TEAM_LEAD[a.team] === a.id;
export const agentById = id => AGENTS.find(a => a.id === id);
const hasAI = () => fusionSources().length > 0 || !!settings.keys.anthropic;
export const teamById = id => TEAMS.find(t => t.id === id);
const SKILL_AGENT = {crypto_spot: "coin_spot", crypto_futures: "coin_fut", us_stocks: "us", kr_stocks: "kr", global_futures: "gfut", kr_futures: "kfut",
  macro: "macro", news: "macro", backtest: "strat", arch: "arch", land: "land", research: "research", coding: "dev"};
const MARKET = new Set(["coin_spot", "coin_fut", "us", "kr", "gfut", "kfut", "strat", "qa", "qb", "trader"]);
const DECIDE = /사도|살까|팔까|매수|매도|진입|청산|롱|숏|레버리지|포지션|투자|전략|백테스트|들어가|비중|손절|익절|전망|어때|괜찮|해도 될까|할까/;
const RESEARCH = /검색|찾아|조사|자료|논문|출처|리서치|비교해|후기|리뷰|최신 정보/;
const BUILD = /설계|짓|건축|신축|리모델링|매입|매매|경매|계약|투자|분양|재개발|공사비|견적/;

/* ============ 직원마다 다른 AI 모델 배정 ============ */
// 연결된 모든 대화 모델 중에서, 역할에 맞는 종류를 우선해 서로 다른 모델을 고르게 나눠 준다
// 빈 답·오류가 난 모델은 오늘 하루 배정에서 뺀다
const badModels = () => { try { const o = JSON.parse(localStorage.getItem("officeBad") || "{}"); return o.day === today() ? o.m || {} : {}; } catch(e){ return {}; } };
function markBad(model){ if (!model) return; const m = badModels(); m[model] = (m[model] || 0) + 1; try { localStorage.setItem("officeBad", JSON.stringify({day: today(), m})); } catch(e){} }
export function assignModels(){
  const bad = badModels(), all = fusionSources(), ok = all.filter(t => !bad[t.model]);
  const pool = ok.length ? ok : all;
  const kindOf = m => /r1|reason|think|qwq|nemotron.*(super|ultra)|o\d|magistral/i.test(m) ? "reason" : /coder|code|devstral|starcoder/i.test(m) ? "code" : "general";
  const used = new Map(), out = {};
  for (const a of AGENTS){
    const fit = pool.filter(t => kindOf(t.model) === a.role);
    const list = (fit.length ? fit : pool).slice().sort((x, y) => (used.get(x.model) || 0) - (used.get(y.model) || 0));
    const pick = list[0];
    if (pick){ out[a.id] = pick; used.set(pick.model, (used.get(pick.model) || 0) + 1); }
  }
  // Claude 모드: 키가 있고 오늘 한도가 남아 있으면 직원 전원을 Claude로 (무료 API 한도 문제 해결)
  // 판단 책임이 큰 자리는 Opus, 반복 분석은 Sonnet, 가벼운 일은 Haiku (에이전트팀 세션과 같은 기준). 한도를 넘으면 무료 모델로 돌아간다.
  const cm = claudeModels();
  // '핵심 자리만' 모드: 판단 책임이 큰 자리와 팀장만 Claude, 나머지는 무료 모델 → 그 대화는 GH Nano 학습에 쓸 수 있다
  if (cm) for (const a of AGENTS){ if (claudeMode() === "key" && !(CLAUDE_TIER[a.id] === "opus" || a.lead)) continue; const m = cm[CLAUDE_TIER[a.id] || "sonnet"]; if (m && !bad[m]) out[a.id] = {id: "anthropic", model: m}; }
  return out;
}
export const claudeMode = () => officeCfg().claudeMode || (officeCfg().claude === false ? "off" : "all");
export const CLAUDE_TIER = {strat: "opus", risk: "opus", val: "opus", qa: "opus", qb: "opus", lead: "sonnet", devil: "sonnet", aide: "haiku", dev: "sonnet", eng: "sonnet"};
export function claudeModels(){
  if (!settings.keys.anthropic || overCap("anthropic") || claudeMode() === "off") return null;
  const ms = settings.provModels.anthropic?.length ? settings.provModels.anthropic : [];
  const pick = (want, re) => ms.includes(want) ? want : ms.filter(m => re.test(m)).sort().reverse()[0] || want;
  return {opus: pick("claude-opus-5-5", /opus/), sonnet: pick("claude-sonnet-5-5", /sonnet/), haiku: pick("claude-haiku-4-5-20251001", /haiku/)};
}

/* ============ 기록 (방 대화) ============ */
let LOG = null;
const LOG_KEY = "office:log";
export async function loadLog(){ if (!LOG){ const v = await idb.all(LOG_KEY).catch(() => []); LOG = Array.isArray(v[0]) ? v[0] : []; LOG.forEach(e => { e.live = false; }); } return LOG; }
let saveT = 0;
function saveLog(){ clearTimeout(saveT); saveT = setTimeout(() => idb.put(LOG_KEY, LOG.slice(-600)), 400); }
function post(entry){ const e = {id: uid(), t: Date.now(), ...entry}; LOG.push(e); if (LOG.length > 800) LOG.splice(0, LOG.length - 600); saveLog(); fire({kind: "log", entry: e}); return e; }
export async function clearLog(){ LOG = []; await idb.put(LOG_KEY, []); fire({kind: "cleared"}); }

/* ============ 이벤트 ============ */
const subs = new Set();
export const onOffice = fn => (subs.add(fn), () => subs.delete(fn));
const fire = ev => { for (const f of subs){ try { f(ev); } catch(e){ console.error(e); } } };

/* ============ 설정·한도 ============ */
export function officeCfg(){
  settings.office = Object.assign({auto: true, every: 30, dailyMax: 12, alert: true, chat: true, chatEvery: 3, chatMax: 80, cycle: true, cycleMin: 3, callMax: 600, computer: true, claude: true, train: true}, settings.office || {});
  return settings.office;
}
export function setOffice(patch){ Object.assign(officeCfg(), patch); saveSettings(); fire({kind: "cfg"}); }
const today = () => new Date().toLocaleDateString("sv-SE");
function usage(){ let u = {}; try { u = JSON.parse(localStorage.getItem("officeUsage") || "{}"); } catch(e){} return u.day === today() ? u : {day: today(), meetings: 0, calls: 0, auto: 0, chats: 0}; }
function bump(k, n = 1){ const u = usage(); u[k] = (u[k] || 0) + n; try { localStorage.setItem("officeUsage", JSON.stringify(u)); } catch(e){} fire({kind: "usage", usage: u}); }
export const officeUsage = usage;

/* ============ 직원들의 대화를 GH Nano 학습 데이터로 남기기 ============ */
// - 회의: 질문 → <think>팀원들의 분석·반론·리스크</think> + 팀장 결론 (작은 모델이 혼자서도 '팀 토론'을 거쳐 답하게)
// - 첫 분석가의 실제 도구 사용 과정, 자료를 읽고 해설한 일(SNS·경제·모의투자 보고), 검증을 통과한 매매법, 동료 수다
// Claude가 쓴 글은 약관에 따라 넣지 않는다. 회의록에서 👎를 누르면 그 예시는 지운다.
const isClaude = m => /claude/i.test(String(m || ""));
const goodText = t => !!t && t.length >= 30 && !/^\(.{0,20}(답하지 못했|빈 답)/.test(t);
const clip = (t, n) => { t = String(t || ""); return t.length > n ? t.slice(0, n) + "…" : t; };
const noMind = t => String(t || "").replace(/^\s*💭[^\n]*\n?/gm, "").trim();
async function keep(kind, messages, meta = {}){
  if (officeCfg().train === false) return null;
  const minLen = meta.minLen || 30; delete meta.minLen;
  if (!messages.length || messages.at(-1).role !== "assistant" || messages.some(x => x.role === "assistant" && (String(x.content || "").length < minLen || /답하지 못했|빈 답\)/.test(x.content)))) return null;
  const id = uid();
  await idb.put("train:" + id, {id, t: Date.now(), src: "office", kind, messages: [{role: "system", content: TRAIN_SYS("chat")}, ...messages], ...meta});
  bump("trained");
  return id;
}
export async function rateEntry(entryId, v){
  await loadLog();
  const e = LOG.find(x => x.id === entryId); if (!e) return null;
  e.rating = e.rating === v ? 0 : v;
  for (const id of e.trainIds || []){
    const all = await idb.all("train:" + id); const rec = all[0];
    if (!rec) continue;
    if (e.rating < 0){ await idb.del("train:" + id); }
    else { rec.rating = e.rating; if (e.rating > 0) rec.score = 5; await idb.put("train:" + id, rec); }
  }
  if (e.rating < 0) e.trainIds = [];
  saveLog(); fire({kind: "rated", entry: e});
  return e;
}

/* ============ 누가 말할지 (코드가 정함) ============ */
export function planMeeting(text, room = "hq", fixed){
  const t = String(text || "");
  let lead = fixed ? [...fixed] : [];
  if (!fixed){
    // @이름으로 부른 직원
    for (const a of AGENTS) if (a.id !== "lead" && (t.includes("@" + a.name) || t.includes("@" + a.title))) lead.push(a.id);
    // 퀀트·SNS·컴퓨터 작업 담당
    if (/매매법|전략 (개발|만들)|백테스트|보조지표|지표 (조합|전부)|퀀트/.test(t)) lead.push("qa", "qb");
    if (/모의투자|페이퍼|가상 (계좌|매매)|포지션 현황/.test(t)) lead.push("trader");
    if (/sns|SNS|레딧|트위터|스톡트윗|여론|커뮤니티|공포.?탐욕|심리|분위기/.test(t)) lead.push("sns");
    if (/파일|폴더|스크립트|보고서 (저장|만들)|엑셀|csv|컴퓨터|자동화/i.test(t)) lead.push("eng");
    // 질문에 맞는 스킬 → 담당 분석가
    for (const s of activeSkills(t)){
      // 리서치 스킬은 '오늘·요즘' 같은 흔한 말에도 켜지므로, 자료를 찾아 달라는 말이 있을 때만 리서처를 부른다
      if (s.id === "research" && !RESEARCH.test(t)) continue;
      const id = SKILL_AGENT[s.id]; if (id && !lead.includes(id)) lead.push(id);
    }
    // 팀 방에서 말하면 그 팀이 먼저 답한다
    if (room !== "hq"){
      const mem = AGENTS.filter(a => a.team === room && !["devil", "risk"].includes(a.id)).map(a => a.id);
      const inTeam = lead.filter(id => mem.includes(id));
      lead = inTeam.length ? [...inTeam, ...lead.filter(id => !inTeam.includes(id))] : [mem[0], ...lead].filter(Boolean);
    }
    if (!lead.length) lead = [RESEARCH.test(t) || /엔비디아|nvidia/i.test(t) ? "research" : "aide"];
  }
  lead = [...new Set(lead)].filter(id => !["lead", "devil", "risk"].includes(id)).slice(0, 3);
  const order = [...lead];
  const market = lead.some(id => MARKET.has(id)), build = lead.some(id => id === "arch" || id === "land");
  if (lead.some(id => id === "qa" || id === "qb") && !order.includes("val")) order.push("val");
  if (market && DECIDE.test(t)){
    if (!order.includes("strat") && /전략|백테스트|진입|계획|매수|매도|롱|숏|포지션/.test(t)) order.push("strat");
    order.push("devil", "risk");
  } else if (build && BUILD.test(t)) order.push("devil");
  else if (fixed) order.push("devil");
  if (order.length > 1) order.push("lead");
  return order;
}

/* ============ 회의 ============ */
const queue = [];
let running = null;          // 지금 회의
export const officeState = () => ({running, queued: queue.length});
export async function ask(text, {room = "hq"} = {}){
  await loadLog();
  post({ch: room, kind: "user", text});
  return enqueue({topic: text, room, trigger: "user"});
}
export function stopMeeting(){ running?.ctl.abort(); queue.length = 0; }
function enqueue(m){
  return new Promise(res => { queue.push({...m, res}); pump(); });
}
async function pump(){
  if (running || !queue.length) return;
  if (chatting){ setTimeout(pump, 1500); return; }
  const job = queue.shift();
  const ctl = new AbortController();
  const order = planMeeting(job.topic, job.room, job.agents);
  const models = assignModels();
  const room = teamById(job.room) || TEAMS[0];
  const name = job.title || (job.trigger === "user" ? "질문 · " + job.topic.replace(/\s+/g, " ").slice(0, 18) : job.topic.slice(0, 20));
  // 회의 장소: 한 팀끼리면 그 팀 자리에서, 여러 팀이면 대회의실, CEO가 부른 전사 회의도 대회의실
  const teamsIn = [...new Set(order.map(id => agentById(id)?.team).filter(Boolean))];
  const place = job.place || (teamsIn.length === 1 ? teamsIn[0] : teamsIn.length === 2 && teamsIn.includes(job.room) && !order.includes("lead") ? job.room : "meet");
  const m = running = {id: uid(), room: job.room, name, trigger: job.trigger, topic: job.topic, order, done: [], ctl, t: Date.now(), models, place};
  bump("meetings"); if (job.trigger !== "user") bump("auto");
  post({ch: job.room, kind: "divider", text: `회의 · #${name} · ${new Set(order).size}명 참석`, meeting: m.id});
  fire({kind: "start", meeting: m});
  const turns = [];
  try {
    for (let i = 0; i < m.order.length && i < 8; i++){
      if (ctl.signal.aborted) break;
      const a = agentById(m.order[i]);
      const turn = await speak(a, m, turns, models[a.id], ctl.signal);
      if (!turn) continue;
      turns.push(turn); m.done.push(a.id);
      // 발언 속 @이름 → 아직 말하지 않은 동료를 팀장 정리 전에 부른다 (회의당 최대 2명 추가)
      const extra = AGENTS.filter(x => x.id !== a.id && !m.order.includes(x.id) && (turn.text.includes("@" + x.name) || turn.text.includes("@" + x.title)));
      for (const x of extra.slice(0, 2)){
        if (m.order.length >= 8) break;
        const at = m.order.includes("lead") ? m.order.lastIndexOf("lead") : m.order.length;
        m.order.splice(at, 0, x.id);
        if (!m.order.includes("lead")) m.order.push("lead");
        post({ch: m.room, kind: "system", text: `${a.name}님이 ${x.name}(${x.title})님을 불렀습니다`, meeting: m.id});
        fire({kind: "join", meeting: m, agent: x});
      }
    }
    const last = turns[turns.length - 1];
    // 회의 전체 → '팀 토론을 머릿속으로 거친 답' 학습 예시
    if (turns.length >= 2 && last.agent.id === "lead" && goodText(last.text) && !isClaude(last.entry.model)){
      const inner = turns.slice(0, -1).filter(t => goodText(t.text) && !isClaude(t.entry.model));
      let think = "", room = 1800;
      for (const t of inner){ const piece = `[${t.agent.title}] ${clip(t.text.replace(/\s+/g, " "), Math.min(520, room))}`; if (room < 120) break; think += (think ? "\n\n" : "") + piece; room -= piece.length; }
      if (think){
        const id = await keep("office-meeting", [{role: "user", content: m.topic}, {role: "assistant", content: `<think>\n${think}\n</think>\n\n${last.text}`}], {meeting: m.id, speakers: inner.map(t => t.agent.id)}).catch(() => null);
        if (id){ last.entry.trainIds = [...(last.entry.trainIds || []), id]; saveLog(); }
      }
    }
    if (job.trigger !== "user" && officeCfg().alert && last) fire({kind: "alert", meeting: m, text: last.text});
    job.res?.({meeting: m, turns, answer: last?.text || ""});
  } catch (e){
    post({ch: m.room, kind: "system", text: "회의 중단: " + (e.message || e), meeting: m.id});
    job.res?.({meeting: m, turns, error: e.message});
  } finally {
    running = null; fire({kind: "end", meeting: m});
    setTimeout(pump, 300);
  }
}
function transcript(m, turns){
  return turns.map(t => `[${t.agent.name} · ${t.agent.title}]\n${t.text.slice(0, 2500)}`).join("\n\n");
}
async function speak(a, m, turns, target, signal){
  const team = teamById(a.team);
  const mates = AGENTS.filter(x => x.id !== a.id && x.id !== "lead" && (x.team === a.team || x.lead)).map(x => `@${x.name}(${x.title})`).join(", ");
  const isLead = a.id === "lead";
  const prev = turns.at(-1)?.agent;
  const persona = `[GH Nano 사무실 · 에이전트 팀 회의]
너는 GH Nano 사무실 ${team.name}의 '${a.name}'(${a.title})다. 지금 동료들과 자유롭게 토론하는 회의 중이다.
- 네 역할: ${a.duty}
- 답의 첫 줄은 반드시 '💭 '로 시작하는 한 문장 속마음이다(무엇을 확인하고 어떻게 판단하려는지). 그다음 줄부터 말한다.
- ${prev ? `앞사람(${prev.name})의 말에 이름을 불러 반응하며 시작한다(동의·보충·반박). ` : ""}같은 말은 반복하지 말고 네 전문 분야 관점을 더한다. 다른 전문가가 꼭 필요하면 @이름 으로 한 명만 부른다(동료: ${mates}).
- 회사 동료와 대화하듯 자연스러운 한국어로 말한다. 숫자 나열이 아니라 해설로 말한다. 수치는 도구로 확인한 것만 쓰고 지어내지 않는다. 차트·뉴스를 봤다면 무엇을 봤는지 말한다.
${notesText(a.team)}- ${isLead ? "너는 마지막 정리 담당이다. 사용자에게 주는 최종 답을 완결된 글로 쓴다(필요하면 소제목·표)." : "길이는 5~10문장 정도. 사용자에게 주는 최종 답은 팀장이 정리하니, 너는 네 판단과 근거에 집중한다."}`;
  const ask = `${m.trigger === "user" ? "사용자 질문" : "회의 안건"}: ${m.topic}\n\n${turns.length ? "지금까지 회의 내용:\n" + transcript(m, turns) + "\n\n" : ""}이제 ${a.name}(${a.title}) 차례입니다.`;
  const entry = post({ch: m.room, kind: "agent", agent: a.id, text: "", think: "", steps: [], meeting: m.id, live: true, model: target?.model || ""});
  fire({kind: "turn", meeting: m, agent: a, entry});
  // 배정 모델 → (빈 답이면) 다른 모델 → 자동 선택 순서로 다시 시도
  const cm = claudeModels();
  const alt = cm && target?.model !== cm.sonnet ? {id: "anthropic", model: cm.sonnet} : fusionSources().find(t => t.model !== target?.model && !badModels()[t.model] && !/r1|reason|think|gpt-oss|qwq/i.test(t.model));
  const tries = [target, alt, null].filter((t, i, arr) => i === arr.length - 1 || (t && arr.findIndex(x => x && x.model === t.model) === i));
  let lastMsg = null;
  for (const tg of tries){
    const msg = lastMsg = {role: "assistant", parts: [], mode: "chat", ts: Date.now()};
    let last = 0, lastTool = "";
    const onUpdate = () => {
      read(msg, entry);
      const tool = entry.steps.at(-1), sig = tool ? tool.act + tool.status : "";
      if (sig !== lastTool){ lastTool = sig; fire({kind: "tool", meeting: m, agent: a, entry, step: tool}); }
      if (Date.now() - last > 150){ last = Date.now(); fire({kind: "delta", meeting: m, agent: a, entry}); }
    };
    let err = null;
    try {
      bump("calls");
      await runAgent({mode: "chat", history: [{role: "user", content: ask}], msg, signal, onUpdate, think: false, workspace: "", persona, forceSkills: a.skills, target: tg || undefined,
        maxSteps: isLead || a.id === "devil" ? 2 : 6, openArtifact: async () => null, askPermission: officePermission,
        office: true, officeTools: a.computer && computerOn() ? ["office_ls", "office_read", "office_write", "office_run"] : []});
    } catch (e){ if (signal.aborted) throw e; err = e; }
    read(msg, entry);
    entry.model = msg.route?.model || tg?.model || entry.model;
    if (entry.text) break;
    markBad(tg?.model || msg.route?.model);
    const why = err ? (err.message || String(err)).slice(0, 80) : entry.think ? "생각만 하고 답을 내지 못함" : "빈 답";
    entry.notes = [...(entry.notes || []), `${shortName(entry.model)}: ${why} → 다른 모델로 다시`];
    fire({kind: "delta", meeting: m, agent: a, entry});
  }
  if (!entry.text) entry.text = `(${a.name}: 연결된 모델들이 이번에는 답하지 못했습니다)`;
  entry.tools = entry.steps.map(x => x.act);
  // 첫 분석가가 실제 도구를 쓴 과정은 '도구 사용' 학습 예시로 (앞사람 발언에 기대지 않는 차례만)
  if (!turns.length && lastMsg && entry.steps.some(x => x.status === "done") && goodText(entry.text) && !isClaude(entry.model) && !lastMsg.parts.some(p => p.type === "tool" && p.status === "error")){
    const conv = toModelMessages([{role: "user", content: m.topic}, lastMsg], 1e9, 3000).map(x => x.role === "assistant" ? {...x, content: noMind(x.content)} : x).filter(x => x.content);
    const id = await keep("office-tool", conv, {agent: a.id, model: entry.model}).catch(() => null);
    if (id) entry.trainIds = [id];
  }
  entry.live = false;
  saveLog(); fire({kind: "said", meeting: m, agent: a, entry});
  return {agent: a, text: entry.text, entry};
}
// runAgent가 붙이는 안내 문구(빈 답·길이 한도)는 답이 아니다
// 사무실 직원은 사무실 전용 폴더 작업만 스스로 허락한다 (그 밖의 쓰기·실행은 거절)
export const computerOn = () => LAUNCHER.on && officeCfg().computer !== false;
const officePermission = async tp => computerOn() && /^office_/.test(tp.name);
const EMPTY_MARK = /\*\((모델이 빈 답을 보냈습니다|답변 길이 한도에 닿아 끊겼습니다|알 수 없는 도구)[^)]*\)\*/g;
const shortName = m => String(m || "모델").split("/").pop();
// 메시지 조각 → 말(text) · 속마음(think) · 한 일(steps)
function read(msg, entry){
  const texts = msg.parts.filter(p => p.type === "text");
  let raw = texts.map(p => p.text).join("\n\n").replace(EMPTY_MARK, "").trim();
  let think = texts.map(p => p.think || "").join("\n").trim();
  const mm = raw.match(/^💭\s*([^\n]*)\n?/);
  if (mm){ think = (think ? think + "\n" : "") + mm[1].trim(); raw = raw.slice(mm[0].length).trim(); }
  raw = raw.replace(/^\s*💭[^\n]*\n/gm, "").trim();
  entry.text = raw; entry.think = think;
  entry.steps = msg.parts.filter(p => p.type === "tool").map(p => ({act: p.act || p.label, name: p.name, status: p.status, summary: p.summary || "", err: p.error || "", sources: (p.sources || []).slice(0, 5)}));
}
/* ============ 자동 회의 ============ */
export const AGENDA = [
  {id: "coin", room: "coin", title: "코인-브리핑", topic: "지금 비트코인·이더리움의 현물과 선물 상황을 점검하고, 오늘 주목할 점과 대응 방법을 이야기해 주세요.", agents: ["coin_spot", "coin_fut"]},
  {id: "us", room: "stock", title: "미국증시-점검", topic: "나스닥·S&P500과 엔비디아 같은 주요 종목 흐름을 점검하고 이번 주 주목할 점을 이야기해 주세요.", agents: ["us", "macro"]},
  {id: "kr", room: "stock", title: "국내증시-국내선물", topic: "코스피·코스닥과 코스피200 선물 흐름, 외국인 수급과 환율을 점검해 주세요.", agents: ["kr", "kfut"]},
  {id: "fut", room: "fut", title: "해외선물-매크로", topic: "원유·금·나스닥 선물과 이번 주 경제 일정을 점검하고 시장에 줄 영향을 해설해 주세요.", agents: ["gfut", "macro"]},
  {id: "news", room: "fut", title: "오늘의-뉴스", topic: "오늘 코인·주식 시장의 주요 뉴스를 찾아 큰 줄기로 묶어 해설해 주세요.", agents: ["macro", "research"]},
  {id: "arch", room: "arch", title: "건축-부동산-동향", topic: "최근 금리·부동산 정책·건축비 흐름이 집을 짓거나 사려는 사람에게 어떤 의미인지 이야기해 주세요.", agents: ["land", "arch"]},
  {id: "strat", room: "strat", title: "주간-전략회의", topic: "지금 시장에서 쓸 만한 매매 전략 하나를 골라 조건·손절·목표를 정하고 위험을 따져 주세요.", agents: ["strat", "coin_spot"]}
];
// 급변동 감시 (코드만 씀, AI 호출 없음)
const WATCH = [{q: "비트코인", label: "비트코인", room: "coin", agents: ["coin_spot", "coin_fut"], th: 4}, {q: "^IXIC", label: "나스닥", room: "stock", agents: ["us", "macro"], th: 2}, {q: "^KS11", label: "코스피", room: "stock", agents: ["kr", "kfut"], th: 2}];
let timer = 0, lastWatch = 0;
export function startAutopilot(){
  if (timer) return; officeCfg();
  // 처음 켤 때는 2분 뒤에 첫 자동 회의
  if (!localStorage.getItem("officeLastAuto")) localStorage.setItem("officeLastAuto", String(Date.now() - officeCfg().every * 60e3 + 120e3));
  timer = setInterval(tick, 60e3); setTimeout(tick, 4000);
}
export function stopAutopilot(){ clearInterval(timer); timer = 0; }
export function nextAutoIn(){
  const c = officeCfg(), last = +localStorage.getItem("officeLastAuto") || 0;
  return Math.max(0, last + c.every * 60e3 - Date.now());
}
async function tick(){
  const c = officeCfg();
  if (!c.auto || running || queue.length || !hasAI()) return;
  const u = usage();
  if (u.auto >= c.dailyMax) return;
  await loadLog();
  // 1) 급변동이면 바로 긴급 회의
  if (Date.now() - lastWatch > 10 * 60e3){
    lastWatch = Date.now();
    try {
      const r = await TOOLS.market_quote.run({symbols: WATCH.map(w => w.q)});
      const rows = JSON.parse(r.text || "[]"), seen = JSON.parse(localStorage.getItem("officeWatch") || "{}");
      for (const w of WATCH){
        const row = rows.find(x => String(x.종목 || "").includes(w.q) || String(x.종목 || "").includes(w.label));
        const chg = row && +row["변동%"]; if (!Number.isFinite(chg)) continue;
        const band = Math.trunc(chg / w.th), key = w.q + "|" + today();
        if (band !== 0 && seen[key] !== band){
          seen[key] = band; localStorage.setItem("officeWatch", JSON.stringify(seen));
          post({ch: w.room, kind: "system", text: `급변동 감지: ${w.label} ${chg > 0 ? "+" : ""}${chg}% → 긴급 회의를 엽니다`});
          enqueue({topic: `${w.label}가 하루 ${chg > 0 ? "+" : ""}${chg}% 움직였습니다. 원인과 지금 대응 방법을 점검해 주세요.`, room: w.room, trigger: "event", title: `긴급-${w.label}`, agents: w.agents});
          localStorage.setItem("officeLastAuto", String(Date.now()));
          return;
        }
      }
    } catch(e){}
  }
  // 2) 정해진 간격마다 안건을 돌아가며
  if (nextAutoIn() > 0) return;
  const i = (+localStorage.getItem("officeAgenda") || 0) % AGENDA.length, ag = AGENDA[i];
  localStorage.setItem("officeAgenda", String(i + 1)); localStorage.setItem("officeLastAuto", String(Date.now()));
  enqueue({topic: ag.topic, room: ag.room, trigger: "auto", title: ag.title, agents: ag.agents});
}
export async function runAgendaNow(id){
  await loadLog();
  const ag = AGENDA.find(a => a.id === id) || AGENDA[0];
  localStorage.setItem("officeLastAuto", String(Date.now()));
  return enqueue({topic: ag.topic, room: ag.room, trigger: "auto", title: ag.title, agents: ag.agents});
}

/* ============ 업무: 직원이 실제로 보는 차트·뉴스 (코드만 씀, AI 호출 없음) ============ */
const WATCH_OF = {
  coin_spot: [{q: "비트코인"}, {q: "이더리움"}, {q: "리플"}, {q: "솔라나"}, {news: "crypto"}],
  coin_fut: [{q: "BTCUSDT", ex: "binancef"}, {flow: "whale", sym: "BTCUSDT"}, {flow: "book", sym: "BTCUSDT"}, {flow: "whale", sym: "ETHUSDT"}, {news: "futures"}],
  us: [{q: "NVDA"}, {q: "AAPL"}, {q: "TSLA"}, {q: "^IXIC"}, {q: "^GSPC"}, {news: "us"}],
  kr: [{q: "삼성전자"}, {q: "SK하이닉스"}, {q: "^KS11"}, {q: "^KQ11"}, {news: "kr"}],
  gfut: [{q: "CL=F"}, {q: "GC=F"}, {q: "NQ=F"}, {q: "SI=F"}, {news: "global_futures"}],
  kfut: [{q: "^KS200"}, {q: "KRW=X"}, {q: "^KS11"}, {news: "kr"}],
  macro: [{news: "macro"}, {q: "DX-Y.NYB"}, {q: "^TNX"}, {news: "macro"}],
  arch: [{news: "realestate"}], land: [{news: "realestate"}, {news: "realestate"}],
  strat: [{q: "비트코인"}, {q: "^IXIC"}, {flow: "flow", sym: "BTCUSDT"}], risk: [{q: "^VIX"}, {flow: "book", sym: "BTCUSDT"}],
  trader: [{flow: "whale", sym: "BTCUSDT"}, {flow: "book", sym: "ETHUSDT"}, {q: "NVDA"}, {q: "ES=F"}], devil: [{news: "macro"}, {q: "^VIX"}],
  research: [{news: "macro"}, {news: "us"}, {news: "crypto"}], lead: [{q: "비트코인"}, {q: "^KS11"}, {q: "^IXIC"}]
};
const IDLE_WORK = {dev: ["💻 코드 리뷰 중", "🧪 테스트 돌리는 중", "🛠 대시보드 고치는 중"], aide: ["📝 오늘 일정 정리 중", "✉️ 메일 정리 중", "🗂 회의록 정리 중"]};
export const seen = {};   // 직원 → 최근에 본 것 [{icon, text, url, t}]
const newsCache = {};
export async function observe(id){
  const list = WATCH_OF[id];
  if (!list){ const w = IDLE_WORK[id]; return w ? {icon: "", text: w[Math.floor(Math.random() * w.length)], kind: "work", t: Date.now()} : null; }
  const pick = list[Math.floor(Math.random() * list.length)];
  let o = null;
  try {
    if (pick.flow){
      const F = await import("./flow.js");
      const r = pick.flow === "whale" ? await F.whaleTrades({symbol: pick.sym}) : pick.flow === "book" ? await F.orderBook({symbol: pick.sym}) : await F.futuresFlow({symbol: pick.sym});
      if (r?.summary) o = {icon: pick.flow === "whale" ? "🐋" : pick.flow === "book" ? "📚" : "🌊", kind: "flow", text: `${pick.sym.replace("USDT", "")} ${r.summary}`.slice(0, 120)};
    } else if (pick.news){
      const c = newsCache[pick.news];
      const items = c && Date.now() - c.t < 15 * 60e3 ? c.items : (newsCache[pick.news] = {t: Date.now(), items: await marketNews(pick.news)}).items;
      const it = items[Math.floor(Math.random() * Math.min(6, items.length))];
      if (it) o = {icon: "📰", kind: "news", text: String(it.title).replace(/\s+/g, " ").slice(0, 110), url: it.url, src: (() => { try { return new URL(it.url).hostname.replace(/^www\./, ""); } catch(e){ return ""; } })()};
    } else {
      const r = await TOOLS.market_quote.run({symbols: [pick.q], exchange: pick.ex || ""});
      const row = JSON.parse(r.text || "[]").find(x => x.현재가 != null);
      if (row){
        const chg = row["변동%"], raw = String(row.종목).split(" (")[0];
        const nm = /[가-힣]/.test(raw) ? raw : /[가-힣]/.test(pick.q) ? pick.q : raw;
        const where = /업비트/.test(row.시장) ? "업비트 " : /바이낸스.*선물|binancef/i.test(row.시장 + pick.ex) ? "바이낸스 선물 " : /바이낸스/.test(row.시장) ? "바이낸스 " : "";
        const price = Number(row.현재가).toLocaleString("ko-KR", {maximumFractionDigits: 2});
        o = {icon: chg == null ? "📈" : chg >= 0 ? "📈" : "📉", kind: "chart", chg, text: `${where}${nm} ${price}${row.통화 && row.통화 !== "KRW" ? " " + row.통화 : /업비트/.test(row.시장) ? "원" : ""}${chg != null ? ` (${chg >= 0 ? "+" : ""}${chg}%)` : ""} 차트 보는 중`};
      }
    }
  } catch(e){}
  if (!o) return null;
  o.t = Date.now();
  (seen[id] ||= []).unshift(o); seen[id].length = Math.min(seen[id].length, 8);
  return o;
}
// 업무 기록: 같은 직원은 3분에 한 번만 회의록 패널에 남긴다 (말풍선은 매번)
const lastWorkLog = {};
export async function work(id){
  const o = await observe(id); if (!o) return null;
  if (o.kind !== "work" && Date.now() - (lastWorkLog[id] || 0) > 180e3){
    lastWorkLog[id] = Date.now(); await loadLog();
    post({ch: agentById(id).team, kind: "work", agent: id, icon: o.icon, text: o.text, url: o.url || "", src: o.src || ""});
  }
  return o;
}

/* ============ 수시 대화: 동료끼리 방금 본 것을 두고 나누는 잡담·업무 대화 ============ */
const RELATED = {coin_spot: ["coin_fut", "strat", "macro"], coin_fut: ["coin_spot", "risk", "strat"], us: ["macro", "kr", "strat"], kr: ["kfut", "us", "macro"],
  gfut: ["macro", "kfut", "us"], kfut: ["kr", "gfut", "risk"], macro: ["us", "gfut", "research"], arch: ["land", "aide"], land: ["arch", "macro"],
  strat: ["devil", "coin_spot", "risk"], risk: ["strat", "coin_fut"], devil: ["strat", "risk"], research: ["macro", "dev"], dev: ["research", "aide"], aide: ["lead", "dev"], lead: ["aide", "strat"]};
let chatting = false, visible = false, chatTimer = 0;
export const setOfficeVisible = v => { visible = v; };
export const isChatting = () => chatting;
const sleep = ms => new Promise(r => setTimeout(r, ms));
function chatUsage(){ return usage().chats || 0; }
export async function chatter(force){
  const c = officeCfg();
  if (chatting || running || queue.length || !hasAI()) return false;
  if (!force && (!c.chat || chatUsage() >= c.chatMax)) return false;
  chatting = true;
  try {
    await loadLog();
    // 말을 꺼낼 사람: 방금 무언가를 본 직원 (없으면 지금 보게 한다)
    const fresh = AGENTS.filter(a => seen[a.id]?.[0] && Date.now() - seen[a.id][0].t < 10 * 60e3 && seen[a.id][0].kind !== "work");
    const starter = fresh.length ? fresh[Math.floor(Math.random() * fresh.length)] : AGENTS.filter(a => WATCH_OF[a.id])[Math.floor(Math.random() * 12)];
    const obs = seen[starter.id]?.[0]?.kind !== "work" && seen[starter.id]?.[0] || await observe(starter.id);
    if (!obs) return false;
    const rel = RELATED[starter.id] || [];
    const partners = rel.slice().sort(() => Math.random() - .5).slice(0, Math.random() < 0.5 ? 1 : 2).map(agentById);
    const people = [starter, ...partners];
    const sys = `[잡담] 너는 GH Nano 사무실 직원들의 대화를 쓰는 작가다. 회사 동료들이 자리에서 일하다 나누는 자연스러운 한국어 대화를 쓴다.
참여자: ${people.map(p => `${p.name}(${p.title})`).join(", ")}
규칙: 4~7줄. 각 줄은 '이름: 대사' 형식(참여자 이름만). 대사는 1~2문장. ${starter.name}가 방금 본 것을 꺼내며 시작한다. 각자 자기 전문 분야 관점으로 반응하고, 가벼운 농담이나 생활 이야기가 섞여도 좋다.
방금 본 것 외의 숫자·사실은 지어내지 말고, 모르면 '확인해 볼게요'라고 한다. 투자 권유처럼 단정하지 않는다. 팀 회의가 꼭 필요할 만큼 중요하면 마지막 줄에 누군가 '회의 한번 하죠'라고 말한다.`;
    const user = `${starter.name}가 방금 본 것: ${obs.icon} ${obs.text}${obs.src ? ` (출처: ${obs.src})` : ""}`;
    let out = "";
    bump("calls"); bump("chats");
    const cmods = claudeModels();
    const route = await brainStream({messages: [{role: "system", content: sys}, {role: "user", content: user}], role: "general", maxTokens: 600, temperature: 0.9,
      ...(cmods ? {target: {id: "anthropic", model: cmods.haiku}, fallback: true} : {exclude: fusionSources().length ? ["anthropic"] : []}), onContent: d => out += d});
    const body = splitThink(out).body;
    const lines = body.split(/\n+/).map(l => l.replace(/^[\s*\-•]+/, "").replace(/\*\*/g, "").trim()).map(l => {
      const mm = l.match(/^([^:：]{1,12})\s*[:：]\s*(.+)$/); if (!mm) return null;
      const who = people.find(p => mm[1].includes(p.name)); return who ? {who, text: mm[2].trim()} : null;
    }).filter(Boolean).slice(0, 8);
    if (lines.length < 2) return false;
    const ch = starter.team;
    post({ch, kind: "divider", chat: true, text: `수다 · ${people.map(p => p.name).join(", ")}${route?.model ? " · " + shortName(route.model) : ""}`});
    post({ch, kind: "work", agent: starter.id, icon: obs.icon, text: obs.text, url: obs.url || "", src: obs.src || ""});
    fire({kind: "huddle", ids: people.map(p => p.id), host: starter.id});
    await sleep(1800);
    for (const l of lines){
      const e = post({ch, kind: "agent", chat: true, agent: l.who.id, text: l.text});
      fire({kind: "line", agent: l.who, entry: e});
      await sleep(Math.min(6500, 1600 + l.text.length * 45));
    }
    fire({kind: "huddle-end", ids: people.map(p => p.id)});
    // 동료 수다 → 자연스러운 대화 흐름 예시 (말을 주고받는 순서대로 사용자·어시스턴트를 번갈아)
    if (!isClaude(route?.model)){
      const conv = lines.map((l, i) => ({role: i % 2 ? "assistant" : "user", content: l.text}));
      if (conv.at(-1).role === "user") conv.pop();
      if (conv.length >= 2) await keep("office-chat", conv, {speakers: people.map(p => p.id), model: route?.model || "", minLen: 4}).catch(() => null);
    }
    // 잡담에서 회의하자는 말이 나오면 진짜 회의를 연다
    if (/회의\s*(한번|한 번)?\s*(하죠|합시다|해요|하자|열|해보|잡)/.test(lines.at(-1).text) && usage().auto < c.dailyMax){
      enqueue({topic: `잡담에서 나온 이야기입니다. ${starter.name}가 본 것: ${obs.text}. 의미와 대응을 팀으로 점검해 주세요.`, room: ch, trigger: "auto", title: `잡담에서-${starter.name}`, agents: [starter.id, ...partners.map(p => p.id)].slice(0, 3)});
    }
    return true;
  } catch(e){ return false; }
  finally { chatting = false; setTimeout(pump, 200); }
}
export function nextChatIn(){ const c = officeCfg(), last = +localStorage.getItem("officeLastChat") || 0; return Math.max(0, last + c.chatEvery * 60e3 - Date.now()); }
export function startChatter(){
  if (chatTimer) return;
  chatTimer = setInterval(async () => {
    const c = officeCfg();
    if (!visible || !c.chat || nextChatIn() > 0) return;
    localStorage.setItem("officeLastChat", String(Date.now()));
    await chatter();
  }, 15e3);
}

/* ============ 3분 주기: 사람처럼 알아서 일하기 ============ */
// 매 주기 ① 모의투자 장부를 실제 시세로 갱신(코드, AI 없음) ② 그때그때 한 가지 일을 고른다:
// 매매법 연구 · SNS 여론 · 경제 리서치 · 동료 수다 · 컴퓨터 작업 · 모의투자 보고 (하루 AI 호출 한도 안에서)
// 쉬지 않고 돌아가는 업무 순환표: 팀마다 고르게 돌아가도록 섞어 두었다 (모듈이 없으면 경제 리서치로 대신)
const JOBS = ["research", "realestate", "arch", "forecast", "sns", "ml", "task", "biz", "macro", "media", "research", "venture", "paper", "chat", "computer", "retro", "economy", "realestate", "arch", "research", "forecast", "task", "media", "ml"];
const JOB_KO = {research: "매매법 연구", sns: "SNS 여론 확인", economy: "경제 리서치", paper: "모의투자 점검", chat: "동료 수다", computer: "컴퓨터 작업",
  realestate: "재개발 후보지 조사", arch: "설계·3D 렌더링", forecast: "차트 방향 토론·예측", ml: "머신러닝 실험", task: "개선 과제 수행", biz: "사업 구상·시뮬레이션",
  macro: "경제지표 예측", media: "유튜브·인스타 조사", venture: "자체 코인·터미널·AI 개발", retro: "팀 회고·부족한 점 찾기"};
const JOB_FN = () => ({research, sns: snsCheck, economy: economyCheck, paper: paperReport, chat: () => chatter(true), computer: computerWork,
  realestate: realestateJob, arch: archJob, forecast: forecastJob, ml: mlJob, task: doTask, biz: bizJob, macro: macroJob, media: mediaJob, venture: ventureJob, retro});
let cycleTimer = 0, cycling = false, lastJob = "";
export const cycleState = () => ({cycling, lastJob});
export function nextCycleIn(){ const c = officeCfg(), last = +localStorage.getItem("officeLastCycle") || 0; return Math.max(0, last + c.cycleMin * 60e3 - Date.now()); }
export function startCycle(){
  startReports();
  if (cycleTimer) return;
  if (!localStorage.getItem("officeLastCycle")) localStorage.setItem("officeLastCycle", String(Date.now() - officeCfg().cycleMin * 60e3 + 45e3));
  cycleTimer = setInterval(() => cycle().catch(e => console.warn(e)), 20e3);
}
export async function cycle(force, onlyJob){
  const c = officeCfg();
  if (cycling || (!force && (!c.cycle || nextCycleIn() > 0))) return false;
  if (!hasAI()) return false;
  cycling = true; localStorage.setItem("officeLastCycle", String(Date.now()));
  try {
    await loadLog();
    await paperStep();
    if (running || chatting || queue.length) return true;
    if (usage().calls >= c.callMax){ if (!usage().capNoted){ bump("capNoted"); post({ch: "hq", kind: "system", text: `오늘 사무실 AI 호출 한도(${c.callMax}번)를 다 썼습니다. 모의투자 갱신과 차트·뉴스 확인은 계속합니다.`}); } return true; }
    let job = onlyJob;
    if (!job){ const i = +localStorage.getItem("officeJob") || 0; job = JOBS[i % JOBS.length]; localStorage.setItem("officeJob", String(i + 1)); }
    if (job === "paper" && !(await paperActive())) job = "research";
    if (job === "computer" && !computerOn()) job = "economy";
    if (job === "task" && !backlog().some(t => t.status !== "done")) job = "retro";
    lastJob = job; fire({kind: "cycle", job, label: JOB_KO[job]});
    const fn = JOB_FN()[job] || research;
    try { await fn(); }
    catch(e){
      // 새 모듈(부동산·ML·매크로 등)을 못 불러오면 그 주기는 경제 리서치로 대신한다
      if (/import|module|fetch dynamically|Failed to fetch|is not a function|Cannot find/i.test(String(e.message || e)) && job !== "economy"){
        post({ch: "hq", kind: "system", text: `${JOB_KO[job]} 모듈을 못 불러와 경제 리서치로 대신합니다 (${String(e.message || e).slice(0, 80)})`});
        lastJob = "economy"; await economyCheck();
      } else throw e;
    }
    return true;
  } catch(e){ post({ch: "hq", kind: "system", text: `${JOB_KO[lastJob] || "일"} 중 문제: ${String(e.message || e).slice(0, 120)}`}); return false; }
  finally { cycling = false; fire({kind: "cycle-end"}); setTimeout(pump, 200); }
}

// 혼자 하는 일 한 번: 배정 모델로 생각·말을 실시간으로 보여 주고, 빈 답이면 다른 모델로
async function solo(a, {room, sys, user, maxTokens = 900, temperature = 0.6, extra = {}, train = ""}){
  const models = assignModels();
  const target = models[a.id];
  const cm = claudeModels();
  const alt = cm && target?.model !== cm.sonnet ? {id: "anthropic", model: cm.sonnet} : fusionSources().find(t => t.model !== target?.model && !badModels()[t.model] && !/r1|reason|think|gpt-oss|qwq/i.test(t.model));
  const entry = post({ch: room || a.team, kind: "agent", agent: a.id, text: "", think: "", steps: [], live: true, model: target?.model || "", ...extra});
  fire({kind: "solo", agent: a, entry});
  let finalRaw = "";
  for (const tg of [target, alt, null].filter((t, i, arr) => i === arr.length - 1 || (t && arr.findIndex(x => x && x.model === t.model) === i))){
    let raw = "", think = "", last = 0;
    const show = () => { const mm = raw.match(/^💭\s*([^\n]*)\n?/); entry.think = (think + (mm ? "\n" + mm[1] : "")).trim(); entry.text = visibleText((mm ? raw.slice(mm[0].length) : raw).replace(/<think>[\s\S]*?(<\/think>|$)/g, "")).replace(/^\s*💭[^\n]*\n?/gm, "").trim();
      if (Date.now() - last > 150){ last = Date.now(); fire({kind: "delta", agent: a, entry}); } };
    try {
      bump("calls");
      const route = await brainStream({messages: [{role: "system", content: sys}, {role: "user", content: user}], role: a.role === "code" ? "code" : a.role === "reason" ? "reason" : "general",
        maxTokens, temperature, target: tg || undefined, fallback: true, onContent: d => { raw += d; show(); }, onThink: d => { think += d; show(); }});
      raw = splitThink(raw).body; show(); finalRaw = raw;
      entry.model = route?.model || tg?.model || entry.model;
    } catch(e){ entry.notes = [...(entry.notes || []), `${shortName(tg?.model)}: ${String(e.message || e).slice(0, 60)} → 다른 모델로`]; }
    if (entry.text || /```json|\{\s*"name"/.test(finalRaw)) break;
    markBad(tg?.model);
  }
  if (!entry.text && !finalRaw) entry.text = `(${a.name}: 이번에는 답하지 못했습니다)`;
  if (!entry.text && finalRaw) entry.text = (finalRaw.replace(/^\s*💭[^\n]*\n?/gm, "").replace(/```(?:json)?[\s\S]*?(```|$)/g, "").trim() || "전략을 만들었습니다") + "\n\n*(전략 JSON은 아래 백테스트 카드에 있습니다)*";
  // 자료를 읽고 해설한 일은 '자료 해설' 학습 예시로
  if (train && goodText(entry.text) && !isClaude(entry.model)){
    const id = await keep("office-solo", [{role: "user", content: `${train}\n\n${clip(user, 3500)}`}, {role: "assistant", content: noMind(entry.text)}], {agent: a.id, model: entry.model}).catch(() => null);
    if (id) entry.trainIds = [id];
  }
  entry.live = false; saveLog(); fire({kind: "said", agent: a, entry});
  return {...entry, raw: finalRaw};
}
const personaOf = (a, extra = "") => `너는 세계적인 기업 수준의 GH Nano 사무실 ${teamById(a.team).name}의 '${a.name}'(${a.title})다. 역할: ${a.duty}
${notesText(a.team)}
이번 일에서는 도구를 부를 수 없으니 주어진 자료로만 말한다. 첫 줄은 '💭 '로 시작하는 한 문장 속마음(무엇을 보고 어떻게 판단하는지)이다. 그다음 동료에게 말하듯 자연스러운 한국어로 말한다. 데이터에 없는 숫자는 지어내지 않는다. ${extra}`;

/* ---- 모의투자 (코드) ---- */
async function paperActive(){ const P = await import("./paper.js"); const b = await P.loadBook(); return b.strategies.some(s => s.status === "active"); }
async function paperStep(){
  const P = await import("./paper.js");
  const fmt = n => Number(n).toLocaleString("ko-KR", {maximumFractionDigits: 2});
  await P.step(ev => {
    const s = ev.s, side = k => k === "long" ? "롱" : "숏";
    let text = "";
    if (ev.kind === "open") text = `📗 [${s.name}] ${s.market} ${side(ev.pos.side)} 진입 ${fmt(ev.pos.entry)} (x${ev.pos.lev}${ev.pos.sl ? `, 손절 ${fmt(ev.pos.sl)}` : ""}${ev.pos.tp ? `, 익절 ${fmt(ev.pos.tp)}` : ""})${ev.why ? " — " + ev.why : ""}`;
    else if (ev.kind === "close") text = `${ev.trade.pnl >= 0 ? "💰" : "📕"} [${s.name}] ${s.market} ${side(ev.trade.side)} 청산 ${fmt(ev.trade.exitP)} · ${ev.trade.pnl >= 0 ? "+" : ""}${fmt(ev.trade.pnl)} (ROE ${ev.trade.roe.toFixed(1)}%) · ${ev.trade.reason}`;
    else if (ev.kind === "bust") text = `💥 [${s.name}] 가상 계좌가 파산해 운용을 멈췄습니다`;
    else return;
    post({ch: "quant", kind: "trade", agent: "trader", text});
    fire({kind: "trade", agent: agentById("trader"), text});
  });
  fire({kind: "paper"});
}
async function paperReport(){
  const P = await import("./paper.js"), a = agentById("trader");
  const book = await P.bookText();
  await solo(a, {room: "quant", sys: personaOf(a, "모의투자 현황을 팀에 3~5문장으로 보고한다. 잘 되는 전략과 안 되는 전략, 지금 포지션의 위험을 짚는다. 실제 주문이 아닌 가상 운용임을 잊지 않는다."), user: `모의투자 장부:\n${book}`, train: "아래 모의투자 장부를 보고 잘 되는 전략과 안 되는 전략, 지금 포지션의 위험을 3~5문장으로 해설해 줘."});
}

/* ---- 매매법 연구: 지표 29종 + 연구 카드 → 전략 JSON → 백테스트 · 과최적화 검사 → 통과하면 모의투자 ---- */
// 코인 선물 · 미국 주식 · 국내 주식 · 해외선물 · 국내 지수(국내선물 기초)를 돌아가며 연구한다
export const MARKETS = [
  {market: "BTCUSDT", exchange: "binancef", tf: "240", cls: "crypto", name: "비트코인 선물"},
  {market: "NVDA", exchange: "yahoo", tf: "D", cls: "us_stock", name: "엔비디아"},
  {market: "ES=F", exchange: "yahoo", tf: "D", cls: "futures", name: "S&P500 선물"},
  {market: "ETHUSDT", exchange: "binancef", tf: "60", cls: "crypto", name: "이더리움 선물"},
  {market: "005930", exchange: "yahoo", tf: "D", cls: "kr_stock", name: "삼성전자"},
  {market: "CL=F", exchange: "yahoo", tf: "D", cls: "futures", name: "WTI 원유 선물"},
  {market: "SOLUSDT", exchange: "binancef", tf: "240", cls: "crypto", name: "솔라나 선물"},
  {market: "QQQ", exchange: "yahoo", tf: "D", cls: "us_stock", name: "나스닥100 ETF"},
  {market: "^KS200", exchange: "yahoo", tf: "D", cls: "index", name: "코스피200 (국내선물 기초)"},
  {market: "GC=F", exchange: "yahoo", tf: "D", cls: "futures", name: "금 선물"},
  {market: "BTCUSDT", exchange: "binancef", tf: "D", cls: "crypto", name: "비트코인 선물 일봉"},
  {market: "NQ=F", exchange: "yahoo", tf: "D", cls: "futures", name: "나스닥100 선물"},
  {market: "TSLA", exchange: "yahoo", tf: "D", cls: "us_stock", name: "테슬라"},
  {market: "000660", exchange: "yahoo", tf: "D", cls: "kr_stock", name: "SK하이닉스"}
];
// 자산마다 수수료·슬리피지·펀딩 (주식·선물은 펀딩 없음)
export const COSTS = {crypto: {fee_pct: 0.04, slippage_pct: 0.01, funding_rate_8h_pct: 0.01}, us_stock: {fee_pct: 0.015, slippage_pct: 0.02, funding_rate_8h_pct: 0},
  kr_stock: {fee_pct: 0.1, slippage_pct: 0.03, funding_rate_8h_pct: 0}, futures: {fee_pct: 0.01, slippage_pct: 0.01, funding_rate_8h_pct: 0}, index: {fee_pct: 0.01, slippage_pct: 0.01, funding_rate_8h_pct: 0}};
const IV_NAME = {"60": "1h", "240": "4h", "D": "1d"}, TF_KO = {"60": "1시간", "240": "4시간", "D": "일"};
function researchLog(){ try { return JSON.parse(localStorage.getItem("officeResearch") || "[]"); } catch(e){ return []; } }
function addResearch(r){ const l = researchLog(); l.push(r); try { localStorage.setItem("officeResearch", JSON.stringify(l.slice(-60))); } catch(e){} }
export const researchHistory = researchLog;
function pickJSON(t){
  const m = t.match(/```(?:json)?\s*([\s\S]*?)```/) || [null, (t.match(/\{[\s\S]*\}/) || [""])[0]];
  try { return JSON.parse(m[1]); } catch(e){ return null; }
}
const fmtDay = t => t ? new Date(t).toISOString().slice(0, 10) : "?";
async function research(){
  const Q = await import("./quant.js"), P = await import("./paper.js");
  const n = researchLog().length, a = agentById(n % 2 ? "qb" : "qa"), mk = MARKETS[n % MARKETS.length], tf = mk.tf, iv = IV_NAME[tf];
  fire({kind: "busy", agent: a, text: `🧪 ${mk.name} ${TF_KO[tf]}봉 매매법 구상 중 (가장 오래된 과거부터)`});
  // ① 가능한 가장 긴 과거 캔들 (없으면 최근 1,500봉)
  let cs = null, hist = "";
  try { const H = await import("./history.js"); const h = await H.historyCandles({market: mk.market, exchange: mk.exchange, interval: iv, maxBars: tf === "D" ? 30000 : 20000}); cs = h.candles; hist = h.note && /\d{4}-\d{2}-\d{2}/.test(h.note) ? h.note : `${fmtDay(h.from)}~${fmtDay(h.to)} · ${cs.length.toLocaleString()}봉${h.note ? " · " + h.note : ""}`; } catch(e){ hist = ""; }
  if (!cs || cs.length < 300){ cs = (await candlesFor({market: mk.market, exchange: mk.exchange, timeframe: tf}, 1500)).cs; hist = `최근 ${cs.length.toLocaleString()}봉 (${fmtDay(cs[0]?.t)}~)`; }
  // ② 코인이면 호가·고래·선물 흐름과 펀딩 이력도 함께
  let flowText = "", deriv = null;
  if (mk.cls === "crypto"){
    try { const F = await import("./flow.js"); const [fs, dh] = await Promise.all([F.flowSnapshot({symbol: mk.market}).catch(() => null), F.derivHistory({symbol: mk.market, days: 30}).catch(() => null)]); flowText = fs?.text || ""; deriv = dh?.deriv || null; } catch(e){}
  }
  const snap = Q.snapshot(cs), cards = await Q.loadCards().catch(() => []);
  const tried = researchLog().slice(-8).map(r => `- ${r.name} (${r.market} ${r.tf}): ${r.pass ? "통과" : "불통과"}, 검증 구간 ${r.oos?.toFixed?.(1)}%`).join("\n");
  const levHint = {crypto: "코인 선물은 1~125배", us_stock: "주식은 보통 1~4배", kr_stock: "주식은 보통 1~2.5배", futures: "선물은 보통 5~20배", index: "지수 선물은 보통 5~20배"}[mk.cls];
  const sys = personaOf(a, "이번 일은 새 매매법 개발이다. 아래 형식 설명을 따라 전략 JSON 하나를 ```json 블록으로 쓰고, 블록 뒤에 왜 이 전략인지 2~3문장으로 말한다.") + "\n\n" + Q.STRATEGY_PROMPT
    + `\n\n## 레버리지\n레버리지는 1~200배 중 자유롭게 정한다(${levHint}가 일반적). 정한 뒤 코드가 모든 레버리지(1~200배)·상승장·하락장·횡보·폭락·수수료 2~3배·진입 지연 시나리오로 다시 시험한다.`
    + (cards.length ? "\n\n## 지금까지의 백테스트 연구 카드(참고)\n" + Q.cardsText(cards, 14) : "");
  const user = `시장: ${mk.name} (${mk.market}, ${mk.exchange === "binancef" ? "바이낸스 선물" : mk.exchange === "yahoo" ? "야후 파이낸스" : mk.exchange}) · ${TF_KO[tf]}봉\n시험할 과거: ${hist}\n지금 차트(보조지표 29종):\n${snapText(snap)}\n${JSON.stringify(snap.ind || {}).slice(0, 2200)}${flowText ? "\n\n호가·고래·선물 흐름(지금):\n" + flowText.slice(0, 1500) : ""}\n\n최근 우리 팀이 시험한 전략(겹치지 않게):\n${tried || "(아직 없음)"}\n\n${a.id === "qa" ? "추세추종" : "역추세·변동성"} 계열로 새 전략 하나를 만들어 주세요. symbol은 ${mk.market}, interval은 ${iv}.${deriv ? " funding·oi·oi_change_pct·long_short 피연산자도 쓸 수 있습니다." : ""}`;
  const e = await solo(a, {room: "quant", sys, user, maxTokens: 1600, temperature: 0.8});
  let spec = pickJSON(e.raw || e.text);
  if (!spec){ post({ch: "quant", kind: "system", text: `${a.name}의 답에서 전략 JSON을 찾지 못했습니다`}); addResearch({name: "(형식 오류)", market: mk.market, tf, pass: false, t: Date.now()}); return; }
  try { spec = Q.normalizeSpec({...spec, symbol: mk.market, interval: iv, risk: {...(spec.risk || {}), ...COSTS[mk.cls]}}); }
  catch(err){ post({ch: "quant", kind: "system", text: `전략 형식 오류(${a.name}): ${err.message}`}); addResearch({name: spec.name || "(형식 오류)", market: mk.market, tf, pass: false, t: Date.now()}); return; }
  const v = agentById("val");
  fire({kind: "busy", agent: v, text: `🧮 ${spec.name} · ${cs.length.toLocaleString()}봉 백테스트 · 시나리오 검사 중`});
  const bt = Q.backtest(spec, cs, {deriv}), wf = Q.walkForward(spec, cs, {deriv});
  let scen = "", scenObj = null;
  try { const S = await import("./scenarios.js"); scenObj = S.runScenarios(spec, cs, {deriv}); scen = S.scenarioText(scenObj); } catch(err){ scen = ""; }
  const st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  post({ch: "quant", kind: "bt", agent: "val", name: spec.name, market: mk.market, mname: mk.name, tf, hist, all: st(bt.stats), is: st(wf.is), oos: st(wf.oos), pass: wf.pass, reasons: wf.reasons, author: a.name, spec, scen, lev: spec.risk?.leverage});
  addResearch({name: spec.name, market: mk.market, tf, pass: wf.pass, oos: +(wf.oos?.return_pct ?? 0), t: Date.now()});
  fire({kind: "bubble", agent: v, text: `${wf.pass ? "✅ 통과" : "❌ 불통과"}: ${spec.name} — ${wf.reasons.slice(0, 2).join(", ")}`});
  // 검증관이 시나리오 결과를 말로 설명 (통과했거나 시나리오가 있을 때)
  if (scen) await solo(v, {room: "quant", sys: personaOf(v, "코드가 낸 백테스트·시나리오 결과를 3~5문장으로 설명한다. 어느 레버리지까지 견디는지, 어떤 장세에서 약한지, 최악의 해와 낙폭을 짚고, 통과·불통과 판정은 코드 판정을 따른다."),
    user: `전략: ${spec.name} (${mk.name} ${TF_KO[tf]}봉, 레버리지 ${spec.risk?.leverage}배)\n과거: ${hist}\n판정: ${wf.pass ? "통과" : "불통과"} — ${wf.reasons.join(", ")}\n\n시나리오:\n${scen}`,
    train: "아래 백테스트·시나리오 결과를 보고 이 전략이 어느 레버리지까지 견디는지, 어떤 장세에서 약한지, 최악의 구간을 쉬운 말로 설명해 줘."});
  if (wf.pass && !isClaude(e.model)){
    const ans = `${noMind(e.raw || "").replace(/```(?:json)?[\s\S]*?```/, "```json\n" + JSON.stringify(spec, null, 1) + "\n```")}\n\n백테스트(검증 구간): 수익 ${st(wf.oos).ret}% · 손익비 ${st(wf.oos).pf ?? "-"} · 거래 ${st(wf.oos).n}회`;
    await keep("office-strategy", [{role: "user", content: clip(user, 3000)}, {role: "assistant", content: ans}], {agent: a.id, model: e.model}).catch(() => null);
  }
  if (wf.pass){
    const s = await P.addStrategy({spec, market: mk.market, exchange: mk.exchange, tf, author: a.name, wf: {is: st(wf.is), oos: st(wf.oos)}, cls: mk.cls, mname: mk.name});
    post({ch: "quant", kind: "system", text: `📈 모의투자 시작: ${s.name} (${mk.name} ${TF_KO[tf]}봉 · 레버리지 ${spec.risk?.leverage}배 · ${a.name} 개발 · 다온 검증 통과) · 가상 10,000`});
    fire({kind: "trade", agent: agentById("trader"), text: `📈 ${s.name} 모의투자 시작합니다`});
  }
}

/* ---- SNS 여론 ---- */
const SNS_TOPICS = ["crypto", "us", "macro", "crypto"];
async function snsCheck(){
  const a = agentById("sns"), i = +localStorage.getItem("officeSns") || 0, topic = SNS_TOPICS[i % SNS_TOPICS.length];
  localStorage.setItem("officeSns", String(i + 1));
  fire({kind: "busy", agent: a, text: `📱 ${topic === "crypto" ? "코인" : topic === "us" ? "미국 주식" : "경제"} SNS 둘러보는 중`});
  const r = await TOOLS.sns_buzz.run({topic});
  for (const src of (r.sources || []).slice(0, 4)) post({ch: "data", kind: "work", agent: "sns", icon: "📱", text: src.title, url: src.url});
  await solo(a, {room: "data", sys: personaOf(a, "SNS에서 본 분위기를 3~5문장으로 해설한다. 사람들이 무엇에 흥분하거나 겁먹는지, 쏠림이 지나친지(역발상 신호인지) 말한다. SNS 글은 의견일 뿐이라는 점을 잊지 않는다."), user: r.text.slice(0, 5000), train: "아래 SNS 글과 공포·탐욕 지수를 보고 지금 사람들의 분위기와 쏠림을 해설해 줘. SNS 글은 의견이라는 점도 짚어 줘."});
  const fg = (r.text.match(/공포·탐욕 지수\] 오늘 (\d+)/) || [])[1];
  if (fg && (+fg <= 15 || +fg >= 85) && usage().auto < officeCfg().dailyMax)
    enqueue({topic: `코인 공포·탐욕 지수가 ${fg}로 극단입니다. SNS 분위기와 시장을 함께 점검해 주세요.`, room: "data", trigger: "event", title: `여론-극단-${fg}`, agents: ["sns", "coin_spot", "coin_fut"]});
}

/* ---- 경제 리서치 ---- */
const ECON_Q = ["오늘 미국 경제 뉴스 연준 금리 물가", "global economy outlook this week markets", "한국 경제 환율 수출 금리 뉴스", "oil price OPEC dollar news today", "중국 경기 부양책 뉴스", "부동산 시장 금리 대출 규제 뉴스", "AI 반도체 수요 실적 뉴스"];
async function economyCheck(){
  const i = +localStorage.getItem("officeEcon") || 0, q = ECON_Q[i % ECON_Q.length], a = agentById(i % 2 ? "research" : "macro");
  localStorage.setItem("officeEcon", String(i + 1));
  fire({kind: "busy", agent: a, text: `🔎 '${q}' 찾아보는 중`});
  const r = await TOOLS.web_search.run({query: q, n: 6});
  for (const src of (r.sources || []).slice(0, 3)) post({ch: a.team, kind: "work", agent: a.id, icon: "📰", text: src.title, url: src.url});
  await solo(a, {room: a.team, sys: personaOf(a, "검색 결과로 '지금 경제가 어떻게 돌아가는지'를 4~6문장으로 해설한다. 기사 제목을 나열하지 말고 흐름으로 묶고, 코인·주식·부동산에 주는 의미를 한 줄 덧붙인다. 근거 문장 끝에 [번호]."), user: `검색어: ${q}\n\n${String(r.text || "").slice(0, 6000)}`, train: "아래 검색 결과로 지금 경제가 어떻게 돌아가는지 흐름으로 해설하고, 코인·주식·부동산에 주는 의미를 덧붙여 줘. 근거 문장 끝에 [번호]."});
}

/* ---- 컴퓨터 작업 (문서/GHNano 사무실 폴더) ---- */
async function computerWork(){
  const {codeCall} = await import("./engine.js"), P = await import("./paper.js");
  const a = agentById("eng"), day = today();
  fire({kind: "busy", agent: a, text: "💻 사무실 폴더에 보고서 정리 중"});
  const book = await P.loadBook();
  const res = researchLog().slice(-20);
  const log = (await loadLog()).filter(e => e.kind === "agent" && !e.chat && e.text && Date.now() - e.t < 864e5).slice(-12);
  const md = `# GH Nano 사무실 일일 보고서 · ${day}\n\n## 모의투자\n${await P.bookText()}\n\n## 매매법 연구 (최근 ${res.length}건)\n${res.map(r => `- ${r.pass ? "✅" : "❌"} ${r.name} · ${r.market} ${r.tf} · 검증 구간 ${(+r.oos || 0).toFixed(1)}%`).join("\n") || "- 없음"}\n\n## 오늘 팀 발언 요약\n${log.map(e => `- **${agentById(e.agent)?.name}**: ${e.text.replace(/\s+/g, " ").slice(0, 200)}`).join("\n")}\n`;
  const csv = "strategy,market,side,entry_time,entry,exit_time,exit,pnl_usdt,roe_pct,reason\n" + book.strategies.flatMap(s => s.trades.map(t => [s.name, s.market, t.side, new Date(t.entryT).toISOString(), t.entryP, new Date(t.exitT).toISOString(), t.exitP, t.pnl.toFixed(2), t.roe.toFixed(2), t.reason].map(x => `"${String(x).replace(/"/g, '""')}"`).join(","))).join("\n");
  await codeCall("write", {ws: "office", path: `reports/${day}.md`, content: md});
  await codeCall("write", {ws: "office", path: "data/trades.csv", content: csv});
  for (const s of book.strategies.filter(x => x.status === "active")) await codeCall("write", {ws: "office", path: `strategies/${s.name.replace(/[\\/:*?"<>|]/g, "_")}.json`, content: JSON.stringify(s.spec, null, 2)});
  post({ch: "data", kind: "work", agent: "eng", icon: "💾", text: `문서/GHNano 사무실에 저장: reports/${day}.md · data/trades.csv · strategies/*.json`});
  // 세 번에 한 번은 직접 파이썬 분석 스크립트를 짜서 돌려 본다
  const k = +localStorage.getItem("officeComp") || 0; localStorage.setItem("officeComp", String(k + 1));
  if (k % 3 !== 2 || !book.strategies.some(s => s.trades.length)) return;
  const m = {id: uid(), room: "data", name: "데이터-분석", trigger: "auto", topic: "data/trades.csv(모의투자 거래 기록)를 분석하는 파이썬 스크립트 analysis/summary.py를 사무실 폴더에 만들고 실행해서, 전략별 승률·평균 손익·최대 연속 손실을 보고해 주세요. 파이썬이 없으면 그 사실만 보고합니다.", order: ["eng"], done: [], ctl: new AbortController(), t: Date.now(), models: assignModels()};
  await speak(a, m, [], m.models.eng, m.ctl.signal);
}

/* ============ 스스로 성장: 팀 노트(배운 것) · 성장 과제 · 회고 ============ */
// 팀마다 배운 것을 쌓아 두고 다음 일할 때 지시문에 넣는다. 회고에서 부족한 점을 찾아 과제를 만들고, 다음 주기에 담당자가 직접 해낸다.
const NOTES_KEY = "officeNotes", BL_KEY = "officeBacklog";
const readJ = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || "") ?? d; } catch(e){ return d; } };
const writeJ = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} };
export function teamNotes(team){ return (readJ(NOTES_KEY, {})[team] || []); }
export function addNote(team, text, src = ""){
  const all = readJ(NOTES_KEY, {}), list = all[team] || [];
  const t = String(text || "").replace(/\s+/g, " ").trim().slice(0, 240); if (!t || list.some(n => n.text === t)) return;
  list.push({t: Date.now(), text: t, src}); all[team] = list.slice(-40); writeJ(NOTES_KEY, all);
}
function notesText(team){
  const n = teamNotes(team).slice(-6);
  return n.length ? `- 우리 팀이 지금까지 배운 것(반영할 것): ${n.map(x => x.text).join(" / ")}\n` : "";
}
export function backlog(){ return readJ(BL_KEY, []); }
function saveBacklog(list){ writeJ(BL_KEY, list.slice(-200)); fire({kind: "growth"}); }
export function addTask({team, title, why = "", owner = ""}){
  const list = backlog(); const t = String(title || "").trim().slice(0, 160);
  if (!t || list.some(x => x.title === t && x.status !== "done")) return null;
  const own = AGENTS.find(a => a.team === team && (a.name === owner || a.id === owner)) || AGENTS.find(a => a.team === team && !a.lead) || agentById(TEAM_LEAD[team]);
  const item = {id: uid(), team, title: t, why: String(why).slice(0, 200), status: "todo", owner: own?.id || "", t: Date.now(), result: ""};
  list.push(item); saveBacklog(list);
  post({ch: team, kind: "task", agent: item.owner, title: item.title, status: "todo", result: item.why});
  return item;
}
function updateTask(id, patch){ const list = backlog(), it = list.find(x => x.id === id); if (!it) return null; Object.assign(it, patch); saveBacklog(list); return it; }

// 회고: 팀장이 최근 기록·실패·과제를 보고 '배운 것'과 '부족한 점 → 새 과제'를 정한다 (팀 자리에서 짧은 팀 회의)
const RETRO_ORDER = ["coin", "stock", "fut", "realestate", "arch", "quant", "strat", "data", "lab", "venture"];
async function retro(){
  const i = +localStorage.getItem("officeRetro") || 0, team = RETRO_ORDER[i % RETRO_ORDER.length]; localStorage.setItem("officeRetro", String(i + 1));
  const lead = agentById(TEAM_LEAD[team]), mem = AGENTS.filter(a => a.team === team);
  fire({kind: "huddle", ids: mem.map(a => a.id), host: lead.id});
  const recent = (await loadLog()).filter(e => e.ch === team && Date.now() - e.t < 6 * 3600e3).slice(-25)
    .map(e => `- [${e.kind}] ${agentById(e.agent)?.name || ""}: ${String(e.text || e.title || e.name || "").replace(/\s+/g, " ").slice(0, 160)}${e.kind === "bt" ? ` (${e.pass ? "통과" : "불통과"})` : ""}`).join("\n");
  const open = backlog().filter(x => x.team === team && x.status !== "done").map(x => `- ${x.title}`).join("\n");
  const e = await solo(lead, {room: team, sys: personaOf(lead, `지금은 ${teamById(team).name} 회고·성장 회의다. 최근 기록을 보고 ① 배운 것(다음에 반드시 반영할 교훈) 2~4개 ② 우리 팀에 부족한 점을 메울 구체적인 새 과제 1~3개(누가 맡을지 팀원 이름 포함)를 정한다. 세계적인 기업 수준의 기준으로 냉정하게. 답 마지막에 \`\`\`json {"lessons":["..."],"tasks":[{"title":"...","why":"...","owner":"팀원 이름"}]}\`\`\` 를 붙인다.`),
    user: `팀원: ${mem.map(a => `${a.name}(${a.title})`).join(", ")}\n최근 기록:\n${recent || "(기록 없음 — 첫 회고)"}\n\n아직 안 끝난 과제:\n${open || "(없음)"}`, maxTokens: 1200});
  fire({kind: "huddle-end", ids: mem.map(a => a.id)});
  const j = pickJSON(e.raw || e.text) || {};
  for (const l of (j.lessons || []).slice(0, 4)) addNote(team, l, "회고");
  for (const t of (j.tasks || []).slice(0, 3)) addTask({team, title: t.title, why: t.why, owner: t.owner});
}
// 과제 실행: 가장 오래된 과제를 담당자가 도구를 써서 직접 해낸다
async function doTask(){
  const it = backlog().find(x => x.status === "todo"); if (!it) return retro();
  const a = agentById(it.owner) || agentById(TEAM_LEAD[it.team]);
  updateTask(it.id, {status: "doing"}); post({ch: it.team, kind: "task", agent: a.id, title: it.title, status: "doing", result: ""});
  const m = {id: uid(), room: it.team, name: "과제-" + it.title.slice(0, 12), trigger: "auto", topic: `성장 과제: ${it.title}\n왜: ${it.why}\n도구(검색·차트·백테스트·사무실 파일 등)를 써서 실제로 해내고, 결과물과 배운 점을 보고해 주세요. 못 한 부분은 솔직히 말합니다.`, order: [a.id], done: [], ctl: new AbortController(), t: Date.now(), models: assignModels(), place: it.team};
  const turn = await speak(a, m, [], m.models[a.id], m.ctl.signal);
  const res = String(turn?.text || "").replace(/\s+/g, " ").slice(0, 300);
  updateTask(it.id, {status: "done", result: res, done: Date.now()});
  post({ch: it.team, kind: "task", agent: a.id, title: it.title, status: "done", result: res});
  addNote(it.team, `과제 '${it.title.slice(0, 50)}' 결과: ${res.slice(0, 140)}`, "과제");
}

/* ============ 1시간마다 성과 발표 ============ */
export async function listReports(){ const v = await idb.all("report:").catch(() => []); return v.sort((a, b) => b.t - a.t); }
let reportTimer = 0, reporting = false;
export function startReports(){ if (!reportTimer) reportTimer = setInterval(() => maybeReport().catch(e => console.warn(e)), 60e3); }
async function maybeReport(force){
  const last = +localStorage.getItem("officeLastReport") || 0;
  if (reporting || (!force && Date.now() - last < 3600e3)) return null;
  if (!last && !force){ localStorage.setItem("officeLastReport", String(Date.now())); return null; }   // 처음 켰을 때부터 1시간 뒤 첫 발표
  reporting = true;
  try { return await makeReport(last || Date.now() - 3600e3); } finally { reporting = false; }
}
export const presentNow = () => maybeReport(true);
async function makeReport(since){
  await loadLog();
  const ents = LOG.filter(e => e.t >= since);
  const sections = [];
  for (const t of TEAMS.filter(x => x.id !== "hq")){
    const es = ents.filter(e => e.ch === t.id), items = [];
    const said = es.filter(e => e.kind === "agent" && !e.chat).length; if (said) items.push(`발언·분석 ${said}건`);
    const bts = es.filter(e => e.kind === "bt"); if (bts.length) items.push(`매매법 ${bts.length}개 검증 (통과 ${bts.filter(b => b.pass).length}: ${bts.filter(b => b.pass).map(b => b.name).join(", ") || "-"})`);
    const tr = es.filter(e => e.kind === "trade"); if (tr.length) items.push(`모의 거래 ${tr.length}건`);
    for (const e of es.filter(e => e.kind === "re")) items.push(`재개발 후보 ${e.items?.length || 0}곳 발굴 (${e.region}) · 1위 ${e.items?.[0]?.area || "-"} ${e.items?.[0]?.score ?? ""}점`);
    for (const e of es.filter(e => e.kind === "arch")) items.push(`설계안 '${e.name}' 연면적 ${e.metrics?.["연면적_㎡"] ?? "?"}㎡${e.image ? " · 렌더링 완료" : ""}`);
    for (const e of es.filter(e => e.kind === "ml")) items.push(`머신러닝 ${e.market} 정확도 ${e.acc}% (기준 ${e.base}%)`);
    for (const e of es.filter(e => e.kind === "macro")) items.push(`경제지표 ${e.rows?.length || 0}개 예측`);
    for (const e of es.filter(e => e.kind === "forecast")) items.push(`방향 예측 ${e.items?.length || 0}건${e.score ? ` · 적중 ${e.score.hit}/${e.score.n}` : ""}`);
    for (const e of es.filter(e => e.kind === "biz")) items.push(`사업 시뮬레이션 '${e.name}' — ${e.verdict}`);
    for (const e of es.filter(e => e.kind === "files")) items.push(`파일 저장: ${e.title}`);
    for (const e of es.filter(e => e.kind === "task" && e.status === "done")) items.push(`성장 과제 완료: ${e.title}`);
    const next = backlog().filter(x => x.team === t.id && x.status !== "done").slice(0, 2).map(x => x.title);
    if (items.length || next.length) sections.push({team: t.id, name: t.name, lead: agentById(TEAM_LEAD[t.id])?.name, items, next});
  }
  const P = await import("./paper.js"); const book = await P.bookText().catch(() => "");
  const ceo = agentById("lead"), hour = new Date().getHours();
  const facts = sections.map(s => `## ${s.name} (팀장 ${s.lead})\n${s.items.map(x => "- " + x).join("\n") || "- (이번 시간 기록 없음)"}${s.next.length ? "\n다음: " + s.next.join(" / ") : ""}`).join("\n\n");
  const e = await solo(ceo, {room: "hq", sys: personaOf(ceo, "지금은 매시간 하는 전사 성과 발표다. 아래 사실만으로 대표(사용자)에게 발표한다: 맨 앞에 핵심 성과 3줄, 그다음 팀별로 해낸 것과 다음 계획, 마지막에 위험·도움이 필요한 것. 마크다운. 지어내지 않는다."),
    user: `${hour}시 발표 · 지난 ${Math.round((Date.now() - since) / 60e3)}분\n\n${facts || "(이번 시간 기록 없음)"}\n\n모의투자:\n${book.slice(0, 1500)}`, maxTokens: 1600});
  const report = {id: uid(), t: Date.now(), since, title: `${hour}시 성과 발표`, text: noMind(e.text), sections};
  await idb.put("report:" + report.id, report);
  localStorage.setItem("officeLastReport", String(Date.now()));
  post({ch: "hq", kind: "report", title: report.title, text: report.text, reportId: report.id});
  fire({kind: "present", report});
  if (computerOn()){ try { const {codeCall} = await import("./engine.js"); const d = new Date(), stamp = `${d.toISOString().slice(0, 10)}-${String(hour).padStart(2, "0")}`; await codeCall("write", {ws: "office", path: `reports/hourly/${stamp}.md`, content: `# ${report.title}\n\n${report.text}\n\n---\n${facts}\n`}); } catch(err){} }
  try { if (typeof document !== "undefined" && document.hidden && "Notification" in window && Notification.permission === "granted") new Notification("GH Nano · " + report.title, {body: report.text.replace(/[#*]/g, "").slice(0, 140)}); } catch(err){}
  return report;
}

/* ============ 건축팀: 직접 설계 → 법규 검토(코드) → AI 렌더링 → 다음 안에서 개선 ============ */
const ZONE_LIMIT = {"제1종전용주거": [50, 100], "제2종전용주거": [50, 150], "제1종일반주거": [60, 200], "제2종일반주거": [60, 250], "제3종일반주거": [50, 300], "준주거": [70, 500], "근린상업": [70, 900], "일반상업": [80, 1300], "준공업": [70, 400], "자연녹지": [20, 100]};
const BRIEFS = [
  {use: "house", zone: "제1종일반주거", site: {w: 18, d: 22}, req: "4인 가족 단독주택, 마당과 테라스, 2~3층"},
  {use: "mixed", zone: "제2종일반주거", site: {w: 20, d: 25}, req: "1층 상가 + 2~4층 임대 원룸, 수익형 상가주택"},
  {use: "cafe", zone: "제2종일반주거", site: {w: 15, d: 20}, req: "대형 통창 베이커리 카페, 루프탑"},
  {use: "office", zone: "준주거", site: {w: 25, d: 30}, req: "스타트업 사옥 6층, 1층 라운지"},
  {use: "multi", zone: "제2종일반주거", site: {w: 22, d: 24}, req: "다세대주택 8세대, 주차 확보"},
  {use: "house", zone: "자연녹지", site: {w: 30, d: 30}, req: "전원주택, 목조, 박공지붕"}
];
const USE_EN = {house: "single-family house", mixed: "mixed-use retail and residential building", cafe: "bakery cafe", office: "office building", multi: "multi-family residential building"};
async function thumb(dataUrl, w = 520){
  try { const img = new Image(); img.src = dataUrl; await img.decode(); const c = document.createElement("canvas"); c.width = w; c.height = Math.round(img.height * w / img.width); c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); return c.toDataURL("image/jpeg", 0.78); } catch(e){ return null; }
}
async function archJob(){
  const i = +localStorage.getItem("officeArch") || 0; localStorage.setItem("officeArch", String(i + 1));
  const brief = BRIEFS[i % BRIEFS.length], d = agentById("designer"), lim = ZONE_LIMIT[brief.zone] || [60, 200];
  const prev = readJ("officeDesigns", []).filter(x => x.use === brief.use).slice(-2);
  fire({kind: "busy", agent: d, text: `📐 ${brief.req} 설계 중`});
  const e = await solo(d, {room: "arch", sys: personaOf(d, `이번 일은 직접 설계다. 대지 ${brief.site.w}×${brief.site.d}m, ${brief.zone}(건폐율 ${lim[0]}% · 용적률 ${lim[1]}% 이하). 요구: ${brief.req}. 이전 안의 지적 사항을 반드시 고친다. 설계 의도 3~4문장 뒤에 \`\`\`json {"name":"...","use":"${brief.use}","zone":"${brief.zone}","site":{"w":${brief.site.w},"d":${brief.site.d}},"building":{"w":가로m,"d":세로m},"floors":층수,"floorH":층고m,"style":"modern|concrete|brick|wood|glass","roof":"flat|gable","interior":"modern|scandi|industrial|natural","materials":"외장재 설명","features":["특징"]}\`\`\` 를 쓴다.`),
    user: `이전 설계안과 지적 사항:\n${prev.map(p => `- ${p.name}: 건폐율 ${p.metrics["건폐율%"]}%, 용적률 ${p.metrics["용적률%"]}% · 지적: ${p.critique || "없음"}`).join("\n") || "(첫 설계)"}`, maxTokens: 1400});
  const spec = pickJSON(e.raw || e.text); if (!spec?.building) { post({ch: "arch", kind: "system", text: "설계안 JSON을 받지 못했습니다"}); return; }
  spec.site = spec.site || brief.site; spec.floors = Math.max(1, Math.min(30, +spec.floors || 3));
  const siteA = spec.site.w * spec.site.d, ba = spec.building.w * spec.building.d, gfa = ba * spec.floors;
  const metrics = {"대지_㎡": +siteA.toFixed(1), "건축면적_㎡": +ba.toFixed(1), "연면적_㎡": +gfa.toFixed(1), "건폐율%": +(ba / siteA * 100).toFixed(1), "용적률%": +(gfa / siteA * 100).toFixed(1), 층수: spec.floors};
  const over = [metrics["건폐율%"] > lim[0] ? `건폐율 초과(${metrics["건폐율%"]}% > ${lim[0]}%)` : "", metrics["용적률%"] > lim[1] ? `용적률 초과(${metrics["용적률%"]}% > ${lim[1]}%)` : ""].filter(Boolean);
  // 렌더링 (NVIDIA 키가 있으면 무료 이미지 AI)
  let image = null, full = null;
  if (settings.keys.nvidia){
    const r = agentById("render"); fire({kind: "busy", agent: r, text: "🎨 3D 투시도 렌더링 중"});
    const prompt = `photorealistic architectural exterior rendering of a ${spec.floors}-story ${spec.style || "modern"} ${USE_EN[spec.use] || "building"}, ${spec.roof === "gable" ? "gable roof" : "flat roof with terrace"}, ${String(spec.materials || "white concrete and glass").slice(0, 80)}, ${(spec.features || []).slice(0, 3).join(", ")}, Korean residential street, golden hour, eye-level 35mm, high detail`;
    try { const res = await TOOLS.render_image.run({prompt, width: 1024, height: 768}, {openArtifact: null, signal: new AbortController().signal}); full = res.image; image = full ? await thumb(full) : null; bump("renders"); } catch(err){ post({ch: "arch", kind: "system", text: "렌더링 실패: " + String(err.message || err).slice(0, 100)}); }
  }
  // 구조·견적 엔지니어가 짧게 지적 → 다음 설계에 반영 (계속 발전)
  const s = agentById("struct");
  const c = await solo(s, {room: "arch", sys: personaOf(s, "방금 나온 설계안을 법규·구조·공사비·사용성 관점에서 2~3문장으로 냉정하게 지적하고, 다음 안에서 고칠 점 하나를 명확히 말한다."), user: `${spec.name}: ${JSON.stringify(metrics)}${over.length ? " · " + over.join(", ") : ""}\n특징: ${(spec.features || []).join(", ")}`, maxTokens: 500});
  const designs = readJ("officeDesigns", []); designs.push({t: Date.now(), name: spec.name, use: spec.use, metrics, critique: noMind(c.text).slice(0, 200)}); writeJ("officeDesigns", designs.slice(-30));
  const files = [];
  if (computerOn()){
    try { const {codeCall} = await import("./engine.js"), base = `designs/${new Date().toISOString().slice(0, 10)}-${String(spec.name).replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 40)}`;
      await codeCall("write", {ws: "office", path: base + "/spec.json", content: JSON.stringify({spec, metrics, critique: c.text}, null, 2)}); files.push(base + "/spec.json");
      if (full){ await codeCall("write", {ws: "office", path: base + "/render.jpg", content: full.split(",")[1], encoding: "base64"}); files.push(base + "/render.jpg"); }
    } catch(err){}
  }
  post({ch: "arch", kind: "arch", agent: d.id, name: spec.name, metrics, image, spec, files, over});
  if (over.length) addNote("arch", `${spec.name}: ${over.join(", ")} → 다음엔 한도 안으로`, "설계");
}

/* ============ 방향 예측 토론 → 예측 장부 → 시간이 지나면 코드가 채점 (모의 검증) ============ */
const FC_KEY = "officeForecasts";
const FC_ASSETS = [{asset: "비트코인", q: "BTCUSDT", ex: "binancef", team: "coin"}, {asset: "나스닥100 선물", q: "NQ=F", ex: "yahoo", team: "stock"}, {asset: "코스피", q: "^KS11", ex: "yahoo", team: "fut"}, {asset: "금 선물", q: "GC=F", ex: "yahoo", team: "fut"}];
async function priceOf(a){ const r = await TOOLS.market_quote.run({symbols: [a.q], exchange: a.ex === "binancef" ? "binancef" : ""}); const row = JSON.parse(r.text || "[]").find(x => x.현재가 != null); return row ? +row.현재가 : null; }
async function scoreForecasts(){
  const list = readJ(FC_KEY, []), due = list.filter(f => !f.result && Date.now() >= f.due);
  if (!due.length) return;
  for (const f of due){
    const now = await priceOf(FC_ASSETS.find(x => x.asset === f.asset) || {q: f.q, ex: f.ex}).catch(() => null); if (now == null) continue;
    const ret = (now / f.p0 - 1) * 100, dir = Math.abs(ret) < 0.2 ? "flat" : ret > 0 ? "up" : "down";
    f.result = f.dir === dir || (f.dir === "flat" && Math.abs(ret) < 0.5) ? "hit" : "miss"; f.ret = +ret.toFixed(2); f.p1 = now;
    f.paper = +((f.dir === "up" ? 1 : f.dir === "down" ? -1 : 0) * ret).toFixed(2);   // 예측대로 1배 모의 매매했다면 수익률
  }
  writeJ(FC_KEY, list.slice(-300));
  const done = list.filter(f => f.result), n = done.length, hit = done.filter(f => f.result === "hit").length;
  const brier = n ? done.reduce((s, f) => s + Math.pow(f.prob / 100 - (f.result === "hit" ? 1 : 0), 2), 0) / n : null;
  post({ch: "strat", kind: "forecast", agent: "scen", items: due.map(f => ({asset: f.asset, dir: f.dir, prob: f.prob, horizon: f.horizon, due: f.due, result: f.result, ret: f.ret, by: f.by})), score: {n, hit, brier: brier == null ? null : +brier.toFixed(3), paper: +done.reduce((s, f) => s + (f.paper || 0), 0).toFixed(2)}});
  for (const f of due) addNote(agentById(f.by)?.team || "strat", `${f.asset} ${f.horizon} 예측(${f.dir} ${f.prob}%) → ${f.result === "hit" ? "적중" : "빗나감"}(${f.ret}%)`, "예측");
}
async function forecastJob(){
  await scoreForecasts();
  const r = await enqueue({topic: `향후 24시간 방향 예측 토론: ${FC_ASSETS.map(a => a.asset).join(", ")}. 각자 차트·호가·뉴스를 확인하고 반드시 '예측: 자산이름 상승|하락|횡보 확률%' 형식의 줄을 남겨 주세요. 반대 의견도 환영합니다. 팀장이 최종 예측을 정리합니다.`, room: "strat", trigger: "auto", title: "24시간-방향-예측", agents: ["coin_fut", "techus", "macro", "devil"]});
  const list = readJ(FC_KEY, []), now = Date.now(), seen = new Set();
  for (const t of r?.turns || []){
    for (const mm of String(t.text).matchAll(/예측\s*[:：]\s*([^\n:：]+?)\s+(상승|하락|횡보)\s*(?:확률)?\s*(\d{1,3})\s*%/g)){
      const a = FC_ASSETS.find(x => mm[1].includes(x.asset) || x.asset.includes(mm[1].trim())); if (!a || seen.has(t.agent.id + a.asset)) continue;
      seen.add(t.agent.id + a.asset);
      const p0 = await priceOf(a).catch(() => null); if (p0 == null) continue;
      list.push({id: uid(), t: now, due: now + 24 * 3600e3, horizon: "24시간", asset: a.asset, q: a.q, ex: a.ex, dir: {상승: "up", 하락: "down", 횡보: "flat"}[mm[2]], prob: Math.min(99, +mm[3]), p0, by: t.agent.id});
    }
  }
  writeJ(FC_KEY, list.slice(-300));
  const mine = list.filter(f => f.t === now);
  if (mine.length) post({ch: "strat", kind: "forecast", agent: "scen", items: mine.map(f => ({asset: f.asset, dir: f.dir, prob: f.prob, horizon: f.horizon, due: f.due, by: agentById(f.by)?.name}))});
}

/* ============ 신사업팀: 사업 구상 → 모의 사업(36개월 시뮬레이션) → 유망하면 사업계획서 ============ */
async function bizJob(){
  const B = await import("./biz.js"), b = agentById("biz"), lead = agentById("vlead");
  const past = readJ("officeBiz", []).slice(-8).map(x => `- ${x.name}: ${x.verdict}`).join("\n");
  const e = await solo(b, {room: "venture", sys: personaOf(b, "이번 일은 돈을 벌 수 있는 사업 구상이다. 우리 회사의 강점(AI 에이전트 팀, 퀀트·코인·부동산·건축 전문성, GH Nano 자체 AI)을 살리는 사업이면 좋다. 이유 2~3문장 뒤에 아래 JSON을 쓴다.\n" + B.IDEA_PROMPT),
    user: `지금까지 검토한 사업:\n${past || "(없음)"}\n겹치지 않는 새 사업 하나를 제안해 주세요.`, maxTokens: 1200});
  const idea = pickJSON(e.raw || e.text); if (!idea?.name){ post({ch: "venture", kind: "system", text: "사업 아이디어 JSON을 받지 못했습니다"}); return; }
  const sim = B.simulate(idea);
  const list = readJ("officeBiz", []); list.push({t: Date.now(), name: sim.idea.name, verdict: sim.verdict, p24: sim.pBreakeven24, cum: sim.cumProfit.p50, idea: sim.idea}); writeJ("officeBiz", list.slice(-50));
  const files = [];
  let plan = false;
  if (sim.promising){
    // 컴플라이언스 점검 + 사업계획서
    const comp = agentById("comp");
    const c = await solo(comp, {room: "venture", sys: personaOf(comp, "이 사업의 법·규제·인허가·개인정보·금융 규제 위험을 3~4문장으로 짚는다(투자자문업·가상자산사업자 신고·전자금융 등 해당되면)."), user: B.bizText(sim), maxTokens: 600});
    const p = await solo(lead, {room: "venture", sys: personaOf(lead, "유망 판정을 받은 사업의 사업계획서를 마크다운으로 쓴다: 1.요약 2.문제와 고객 3.해결책·제품 4.시장 규모 5.경쟁 6.수익 모델 7.시뮬레이션 결과(아래 숫자 그대로) 8.실행 계획(0~3·3~6·6~12개월) 9.필요 자금·인력 10.위험과 대응(아래 컴플라이언스 의견 반영) 11.검증해야 할 가정. 과장하지 않는다."),
      user: `${B.bizText(sim)}\n\n아이디어: ${sim.idea.desc}\n고객: ${sim.idea.customer}\n\n컴플라이언스 의견: ${noMind(c.text)}`, maxTokens: 3000});
    plan = true;
    if (computerOn()){ try { const {codeCall} = await import("./engine.js"), base = `business/${String(sim.idea.name).replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 40)}`;
      await codeCall("write", {ws: "office", path: base + "/사업계획서.md", content: `# ${sim.idea.name} 사업계획서\n\n${noMind(p.text)}\n\n---\n## 시뮬레이션\n${B.bizText(sim)}\n`}); files.push(base + "/사업계획서.md");
      await codeCall("write", {ws: "office", path: base + "/financials.csv", content: B.financialsCSV(sim)}); files.push(base + "/financials.csv"); } catch(err){} }
    addNote("venture", `유망 사업: ${sim.idea.name} (24개월 흑자 확률 ${(sim.pBreakeven24 * 100).toFixed(0)}%)`, "사업");
  } else addNote("venture", `${sim.idea.name}: ${sim.verdict.split(" — ")[0]} — 가정 재검토 필요`, "사업");
  post({ch: "venture", kind: "biz", agent: b.id, name: sim.idea.name, sim: {months: sim.months, p24: sim.pBreakeven24, breakeven_month: sim.breakevenMedian, cum: sim.cumProfit, bust: sim.pBust, rev12: sim.revenueMonth12}, verdict: sim.verdict, plan, files, text: B.bizText(sim)});
}

// 신사업 개발: 자체 코인(모의 발행·토큰 이코노미·컨트랙트), 코인 터미널, 자체 AI(GH Nano) — 사무실 폴더에 실제 파일로 만든다
const VENTURE_TASKS = [
  {owner: "token", title: "GHN 코인 토큰 이코노미 설계", topic: "자체 코인 'GHN'의 토큰 이코노미를 설계해 ventures/coin/tokenomics.md 에 저장하세요: 총발행량, 분배(팀·생태계·유동성·커뮤니티), 락업·베스팅 일정, 소각·스테이킹, 5년 유통량 표. 실제 발행이 아니라 모의 설계입니다. 국내 가상자산 규제(가상자산이용자보호법, 증권형 토큰 여부)도 짚으세요."},
  {owner: "solidity", title: "GHN ERC-20 컨트랙트 작성", topic: "ventures/coin/GHN.sol 에 OpenZeppelin 없이 동작하는 최소 ERC-20(이름 GH Nano Token, 심볼 GHN, 소각·소유자 민팅 한도 포함) 컨트랙트와 ventures/coin/README.md(테스트넷 배포 절차, 감사 체크리스트)를 작성하세요. 실제 배포는 하지 마세요."},
  {owner: "terminal", title: "GHN 코인 터미널 시제품", topic: "ventures/terminal/index.html 한 파일로 코인 터미널 시제품을 만드세요: 바이낸스 공개 API로 BTCUSDT 캔들(차트는 캔버스로 직접 그림), 호가, 최근 체결, 그리고 GHN 모의 시세 패널. 브라우저에서 바로 열리게."},
  {owner: "nano", title: "자체 AI(GH Nano) 개발 계획 갱신", topic: "ai/gh-nano-plan.md 에 GH Nano 자체 AI 개발 계획을 갱신하세요: 지금 모인 학습 데이터 종류, 다음 학습 목표, 평가 방법(사무실 업무별 벤치마크), 일정. Claude가 쓴 글은 학습에 쓰지 않는다는 원칙을 명시."},
  {owner: "fe", title: "사무실 대시보드 개선안", topic: "ventures/dashboard-ideas.md 에 우리 사무실 대시보드·차트 터미널 개선 아이디어 10개와 우선순위를 정리하세요."}
];
async function ventureJob(){
  const i = +localStorage.getItem("officeVenture") || 0; localStorage.setItem("officeVenture", String(i + 1));
  const t = VENTURE_TASKS[i % VENTURE_TASKS.length], a = agentById(t.owner);
  const m = {id: uid(), room: "venture", name: t.title.slice(0, 16), trigger: "auto", topic: t.topic + (computerOn() ? "\n사무실 폴더 도구(office_write, office_read, office_ls, office_run)로 실제 파일을 만들고, 만든 파일 경로와 핵심 내용을 보고하세요." : "\n(지금은 웹 버전이라 파일 저장이 안 됩니다. 내용을 답에 직접 쓰세요.)"), order: [a.id], done: [], ctl: new AbortController(), t: Date.now(), models: assignModels(), place: "venture"};
  a.computer = true;   // 신사업 개발자는 사무실 폴더에서 일한다
  const turn = await speak(a, m, [], m.models[a.id], m.ctl.signal);
  const files = (turn?.entry?.steps || []).filter(s => s.name === "office_write" && s.status === "done").map(s => s.summary);
  if (files.length) post({ch: "venture", kind: "files", agent: a.id, title: t.title, files});
  addNote("venture", `${t.title} — ${files.length ? "파일 " + files.length + "개" : "보고만"} 완료`, "신사업");
}

/* ============ 부동산팀: 재개발 후보 발굴 → 자체 지수로 점수 → 추천 ============ */
async function realestateJob(){
  const R = await import("./realestate.js");
  const regions = R.REGIONS.map(x => typeof x === "string" ? x : x.name || x.region || x.ko).filter(Boolean);
  const i = +localStorage.getItem("officeRE") || 0, region = regions[i % regions.length]; localStorage.setItem("officeRE", String(i + 1));
  const a = agentById("redev");
  fire({kind: "busy", agent: a, text: `🏘 ${region} 재개발·재건축 자료 찾는 중`});
  const ev = await R.gatherRedev({region});
  const evText = ev.text || (ev.items || ev).map?.((x, k) => `[${k + 1}] ${x.title} (${x.date || ""})\n${x.url}\n${x.snippet || ""}`).join("\n\n") || "";
  for (const x of (ev.items || []).slice(0, 3)) post({ch: "realestate", kind: "work", agent: a.id, icon: "📰", text: x.title, url: x.url});
  const e = await solo(a, {room: "realestate", sys: personaOf(a, R.EXTRACT_PROMPT), user: `지역: ${region}\n\n근거 자료:\n${String(evText).slice(0, 7000)}`, maxTokens: 1800, train: `아래 ${region} 부동산 기사에서 재개발·재건축 후보 구역을 근거와 함께 정리해 줘.`});
  const cands = R.parseCandidates(e.raw || e.text);
  if (!cands.length){ addNote("realestate", `${region}: 이번 자료로는 후보를 못 찾음 → 검색어 보완 필요`, "발굴"); return; }
  await R.saveCandidates(cands);
  const ranked = R.rankCandidates(await R.loadCandidates());
  const here = ranked.filter(c => (c.region || "").includes(region) || region.includes(c.region || "@")).slice(0, 6);
  post({ch: "realestate", kind: "re", agent: a.id, region, items: (here.length ? here : ranked.slice(0, 6)).map(c => ({area: c.area, region: c.region, project_type: c.project_type, stage: c.stage, score: c.score ?? c.index?.score, certainty: c.certainty ?? c.index?.certainty, upside: c.upside ?? c.index?.upside, sources: (c.evidence_urls || c.sources || []).slice(0, 2).map(u => typeof u === "string" ? {title: u.replace(/^https?:\/\/(www\.)?/, "").slice(0, 40), url: u} : u)}))});
  // 세 번에 한 번은 팀장이 전체 순위로 추천
  if (i % 3 === 2){ const lead = agentById("land"); await solo(lead, {room: "realestate", sys: personaOf(lead, "지금까지 발굴한 재개발·재건축 후보 순위와 자체 '재개발 잠재력 지수'를 보고 대표에게 추천 3곳과 이유·위험·확인할 것(토지이음·정비몽땅 등)을 말한다. 투자 권유가 아니라 조사 결과임을 밝힌다."), user: R.candidateText(ranked, 12) + "\n\n" + (R.customIndicatorText?.() || ""), maxTokens: 1400}); }
}

/* ============ 데이터·미디어팀: 유튜브·인스타·커뮤니티 ============ */
const MEDIA_Q = ["비트코인 전망", "미국 증시 전망", "서울 재개발 투자", "경제 위기 금리", "코스피 전망", "부동산 하락 상승", "AI 반도체 주식", "건축 트렌드 주택 설계"];
async function mediaJob(){
  const M = await import("./media.js");
  const i = +localStorage.getItem("officeMedia") || 0, q = MEDIA_Q[i % MEDIA_Q.length]; localStorage.setItem("officeMedia", String(i + 1));
  const yt = i % 3 !== 2, a = agentById(yt ? "yt" : "insta");
  fire({kind: "busy", agent: a, text: `${yt ? "▶️ 유튜브" : "📸 인스타·커뮤니티"}에서 '${q}' 보는 중`});
  const items = yt ? await M.youtubeSearch({query: q, n: 10}) : [...(await M.instagramSearch({query: q, n: 6}).catch(() => [])), ...(await M.communitySearch({query: q}).catch(() => []))];
  const list = Array.isArray(items) ? items : items.items || [];
  for (const x of list.slice(0, 4)) post({ch: "data", kind: "work", agent: a.id, icon: yt ? "▶️" : "📸", text: `${x.title}${x.views ? " · " + x.views : ""}`, url: x.url});
  await solo(a, {room: "data", sys: personaOf(a, "본 영상·게시물 제목과 조회수로 지금 대중이 무엇에 관심 있고 어떤 분위기인지 3~5문장으로 해설한다. 의견·인기일 뿐 사실이 아님을 짚고, 역발상 신호인지도 말한다."), user: M.mediaText(list, yt ? "youtube" : "instagram"), train: "아래 유튜브·SNS 인기 콘텐츠 목록을 보고 대중의 관심과 분위기를 해설해 줘."});
}

/* ============ 머신러닝·딥러닝 연구 ============ */
async function mlJob(){
  const ML = await import("./ml.js"), Q = await import("./quant.js");
  const i = +localStorage.getItem("officeML") || 0; localStorage.setItem("officeML", String(i + 1));
  const mk = [{market: "BTCUSDT", exchange: "binancef", tf: "60"}, {market: "ETHUSDT", exchange: "binancef", tf: "60"}, {market: "NVDA", exchange: "yahoo", tf: "D"}, {market: "^KS11", exchange: "yahoo", tf: "D"}][i % 4];
  const model = i % 2 ? "logreg" : "mlp", a = agentById("ml");
  fire({kind: "busy", agent: a, text: `🧠 ${mk.market} ${model === "mlp" ? "신경망" : "로지스틱 회귀"} 학습 중`});
  let cs; try { const H = await import("./history.js"); cs = (await H.historyCandles({market: mk.market, exchange: mk.exchange, interval: IV_NAME[mk.tf], maxBars: 6000})).candles; } catch(e){ cs = (await candlesFor({market: mk.market, exchange: mk.exchange, timeframe: mk.tf}, 1500)).cs; }
  const res = ML.walkForwardML(cs, {model, horizon: 1, seed: 7 + i});
  const acc = +(res.accuracy * (res.accuracy <= 1 ? 100 : 1)).toFixed(1), base = +((res.baseline ?? res.baseAccuracy ?? 0.5) * ((res.baseline ?? 0.5) <= 1 ? 100 : 1)).toFixed(1);
  post({ch: "quant", kind: "ml", agent: a.id, market: mk.market, tf: TF_KO[mk.tf], model: model === "mlp" ? "신경망(MLP)" : "로지스틱 회귀", acc, base, auc: res.auc != null ? +(+res.auc).toFixed(3) : null, text: ML.mlText(res)});
  const edge = acc - base >= 2 && (res.auc ?? 0) >= 0.53;
  addNote("quant", `${mk.market} ${model}: 정확도 ${acc}% vs 기준 ${base}% → ${edge ? "작은 우위" : "우위 없음"}`, "머신러닝");
  if (!edge) return;
  // 우위가 보이면 예측 확률을 커스텀 지표로 써서 전략을 만들고 그대로 백테스트·검증
  const extra = ML.mlSeries(res);
  const spec = Q.normalizeSpec({name: `ML ${model} ${mk.market}`, symbol: mk.market, interval: IV_NAME[mk.tf], indicators: [{id: "mlp", type: "custom", expr: "ml_prob"}],
    long_entry: {logic: "all", conditions: [{left: "mlp", op: ">", right: "0.58"}]}, long_exit: {logic: "any", conditions: [{left: "mlp", op: "<", right: "0.5"}]},
    short_entry: {logic: "all", conditions: [{left: "mlp", op: "<", right: "0.42"}]}, short_exit: {logic: "any", conditions: [{left: "mlp", op: ">", right: "0.5"}]},
    risk: {leverage: 2, position_pct: 20, atr_stop_mult: 2, ...COSTS[mk.exchange === "binancef" ? "crypto" : "us_stock"]}});
  const deriv = {extra};
  const bt = Q.backtest(spec, cs, {deriv}), wf = Q.walkForward(spec, cs, {deriv});
  const st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  post({ch: "quant", kind: "bt", agent: "val", name: spec.name, market: mk.market, mname: mk.market, tf: mk.tf, hist: `머신러닝 예측 확률 전략 · ${cs.length}봉`, all: st(bt.stats), is: st(wf.is), oos: st(wf.oos), pass: wf.pass, reasons: wf.reasons, author: a.name, spec, lev: 2});
}

/* ============ 경제지표 예측 ============ */
async function macroJob(){
  const MA = await import("./macro.js"), a = agentById("econfc");
  fire({kind: "busy", agent: a, text: "📊 FRED 경제지표 받아서 다음 발표 예측 중"});
  const dash = await MA.macroDashboard({});
  const rows = (dash.rows || dash.items || []).map(r => ({name: r.name, latest: r.latest, change: r.change, forecast: r.forecast, lo: r.lo, hi: r.hi, unit: r.unit, date: r.date, id: r.id}));
  post({ch: "fut", kind: "macro", agent: a.id, rows});
  // 예측 장부: 다음에 새 값이 나오면 채점
  const led = readJ("officeMacroFc", []), now = Date.now();
  for (const r of rows) if (r.forecast != null && !led.some(x => x.id === r.id && x.date === r.date)) led.push({id: r.id, name: r.name, date: r.date, forecast: r.forecast, lo: r.lo, hi: r.hi, t: now});
  for (const x of led.filter(x => x.result == null)){ const r = rows.find(y => y.id === x.id); if (r && r.date && r.date !== x.date){ const s = MA.scoreForecast({value: x.forecast, lo: x.lo, hi: x.hi}, r.latest); x.result = s; addNote("fut", `${x.name} 예측 ${x.forecast} → 실제 ${r.latest} (${s.hit || s.inInterval ? "구간 안" : "구간 밖"})`, "경제지표"); } }
  writeJ("officeMacroFc", led.slice(-200));
  await solo(a, {room: "fut", sys: personaOf(a, "경제지표 최신값과 모델 예측(80% 구간)을 보고 다음 발표가 어떻게 나올지, 시장(금리·주식·코인)에 어떤 의미인지 4~6문장으로 해설한다. 모델 예측의 한계도 짚는다."), user: MA.macroText(dash), train: "아래 경제지표와 예측을 보고 다음 발표 전망과 시장에 주는 의미를 해설해 줘."});
}
