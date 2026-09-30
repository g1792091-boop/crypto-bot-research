# 코인 선물 터미널 (crypto-bot-research)

코인 무기한 선물용 분석·백테스트·페이퍼 트레이딩 터미널이다.
**말로 설명한 진입 기준**을 전략 JSON으로 바꾼 뒤 스스로 백테스트하고 페이퍼 봇으로 돌린다.
사용자는 TradingView 차트에서 보조지표를 조합하며 직접 모의 매매할 수 있다.
AI 에이전트 팀(기술, 파생, 뉴스·매크로 분석가 → 리스크 매니저 → 헤드 트레이더)이 시장을 분석하고 결정을 내린다.

레퍼런스 사이트(Astral, HelloQuant) 분석과 외부 서비스 제약은 [docs/ANALYSIS.md](docs/ANALYSIS.md)에 정리했다.

> ⚠️ 투자 조언이 아니다. 실거래 주문 기능은 없고 모든 매매는 모의(페이퍼)다.

## 화면 구성

| 화면 | 기능 |
|---|---|
| **트레이드** | 관심 종목, 시세 바(24h·펀딩 카운트다운·OI·롱숏·김치 프리미엄·공포탐욕), **터미널 차트**(자체 차트, 지표 개수 제한 없음) / 트레이딩뷰 / 나스닥·매크로, 1분~1년 15개 봉, **1·2·4분할 멀티 차트**, 전체 화면(F), 오버레이(청산맵·고래맵·봇 매매·시나리오선), 수평선·추세선, 시장 판단 + 시나리오, **호가창**(묶음 단위·매수/매도 우위·호가 벽), 모의 주문·가격 알림, 하단 포지션·체결·페이퍼 봇·**거래소 시세**·뉴스·알림 |
| **전략 · 백테스트** | **전략 대화**(말로 만들고 계속 고치기, 매번 백테스트 전·후 비교), 버전 기록·되돌리기, **복기·자동 개선**, 직접 편집, 페이퍼 봇(자동 개선 켜기, 복기 노트, 차트에서 보기) |
| **AI 분석팀** | 기술·파생·뉴스 분석가 → 리스크 한도 → 최종 결정 → 페이퍼 주문 |
| **마켓** | 도미넌스, **공포·탐욕 지수**, **코인글라스 지표**(AHR999·강세장 고점·퓨엘·ETF 순유입 등, 키 필요), 나스닥·S&P·달러·금리·금 미니 차트, 뉴스, 경제지표, 히트맵 |

### 터미널 차트와 자체 보조지표
바이낸스 화면의 차트는 트레이딩뷰에서 유료 라이선스를 받은 것이라 다른 사이트에 넣을 수 없다. 대신 바이낸스 데이터를
lightweight-charts v5 로 직접 그리고, 보조지표 124종을 브라우저에서 계산한다(`frontend/js/ind.js`, Pine 과 같은 공식 —
주요 지표는 백테스트 엔진과 수치가 일치하는지, 나머지는 전부 NaN·길이 오류가 없는지 테스트로 확인).
- 추세: EMA·SMA·WMA·HMA·VWMA·DEMA·TEMA·ALMA·KAMA·ZLEMA·맥긴리·LSMA·RMA·리본·슈퍼트렌드·파라볼릭 SAR·일목·VWAP·피봇·SSL 채널
- 신호 · 패턴(차트에 화살표): 이평 골든/데드 크로스·UT Bot·샹들리에 엑시트·윌리엄스 프랙탈·지그재그(HH/HL/LH/LL)·RSI 다이버전스(히든 포함)
- 레벨 · 프로파일: 볼륨 프로파일(보이는 구간, POC·가치영역)·자동 피보나치·전일/전주 고저·VWAP σ 밴드·선형회귀 채널
- 변동성: 볼린저·켈트너·돈치안·엔벨로프·ATR·밴드폭·%B·초피니스·표준편차·Z-스코어·역사적 변동성·매스 인덱스
- 오실레이터: RSI·스토캐스틱 RSI·스토캐스틱·MACD·PPO·CCI·윌리엄스 %R·MFI·ADX·스퀴즈(압축 점 포함)·웨이브트렌드·어썸·AC·ROC·모멘텀·
  TRIX·아룬·DPO·얼티밋·KST·TSI·CMO·코너스 RSI·피셔·엘더 레이·코폭·보텍스·RVI·샤프 트렌드 사이클·QQE·라게르 RSI·BOP
- 거래량: 거래량·RVOL·시장가 매수 비율·OBV·CMF·CVD·델타·A/D·차이킨 오실레이터·PVT·클링거·포스 인덱스·EOM·거래량 오실레이터
- 파생: OI·OI 변화·펀딩·롱숏·테이커·청산·코인베이스 프리미엄

가격축의 현재가 아래에 **봉 마감까지 남은 시간**을 표시한다(월봉·연봉은 달력 기준, 멀티 차트 칸마다 따로).

### 퀀트 도구 (`backend/app/quant/`, 화면: 퀀트 탭 · 트레이드 오른쪽 '예측')
- **과거 유사 패턴 예측** (`forecast.py`): 최근 48봉의 가격 모양(z-정규화 로그가격)을 과거 3000봉의 모든 구간과 상관계수로
  비교해 겹치지 않는 상위 20개를 고르고(변동성이 너무 다르면 감점), 그 뒤 24봉 흐름을 변동성 비율로 보정해 지금 가격에 이어 붙인다.
  차트에 10~90%·25~75% 부채꼴과 중간값 선으로 그린다.
- **다음 봉 예측**: 수익률·RSI·이평 거리·MACD·거래량·캔들 모양 등 12개 특징의 k-최근접(40) 이웃의 다음 봉 결과로 상승 확률·범위를
  낸다. 최근 150봉을 '그 시점까지의 데이터만으로' 예측해 본 적중률을 '많이 나온 쪽 찍기'와 함께 보여준다(무작위 데이터에서
  찍기 수준인지 테스트로 확인 — 미래 정보 누설 방지).
- **순환매** (`rotation.py`): BTC(또는 시장 평균) 대비 상대강도 회전 그래프(RRG: RS-Ratio = EMA10/EMA40 of RS,
  RS-Momentum = 5봉 변화), 그룹(비트코인·이더리움·대형·중소형·밈)별 수익률로 순환 단계 판정, 모멘텀 상위 K개 순환매
  백테스트(롱 또는 롱·숏 시장중립, 절대 모멘텀 필터, 수수료 반영, BTC·동일비중과 비교).
- **시그널 스캐너** (`scanner.py`): 백그라운드에서 관심 코인 × 봉을 30초마다 검사, 확정 봉 기준 11종 신호(RSI·MACD·EMA 교차·
  슈퍼트렌드·돌파·거래량 급증·스퀴즈 돌파·다이버전스·유동성 스윕·시장 판단 전환·유사 패턴). 같은 방향이 겹치면 강도 상승,
  같은 봉 중복 알림 없음. 설정은 `state/scanner.json`.
- **리스크** (`risk.py`): 수익률 상관 행렬·연 변동성·BTC 베타·VaR/CVaR, 모의 계좌+봇 포지션의 역사적 VaR와 BTC 급락 스트레스,
  백테스트 거래 몬테카를로(부트스트랩 2000회), 파라미터 2개 격자 민감도(학습 70%/검증 30%), 포지션 크기·켈리·변동성 목표 레버리지.

### 체결 · 호가 · 기관식 포트폴리오
- **봉 풋프린트** (`quant/footprint.py`, 차트 '풋프린트'): 봉을 작은 봉(1시간봉 → 1분봉 등)으로 쪼개 작은 봉의 테이커 매수·매도량을
  가격 칸에 나눠 담은 근사 풋프린트. 봉 델타·봉 POC·3배 대각 불균형·3칸 연속 불균형(지지·저항 후보)·델타 다이버전스.
  확대하면 칸마다 '매도 × 매수' 숫자, 축소하면 색.
- **세션 볼륨 프로파일** (지표 '세션 볼륨 프로파일'): 일별 또는 아시아·유럽·미국 세션마다 가격대별 거래량, POC·가치영역,
  다시 닿지 않은 POC(nPOC) 연장, 진행 중 POC·직전 세션 POC/VAH/VAL 선.
- **다음 봉 예측 특징 추가**: 현재 세션 POC 거리 · 직전 세션 POC 거리 · 직전 세션 가치영역 위치 · 10봉 누적 델타 (총 16개) + 근거 설명.
- **종합 진입 판단** (`quant/entry.py`, 예측 탭 맨 위): 시장 판단 · 다음 봉 · 유사 패턴 · 풋프린트 · 호가 불균형을 가중 합산
  (−100~+100). 다음 봉은 적중률이 찍기보다 나을 때만, 유사 패턴은 신뢰도만큼 반영. 호가 벽 또는 시나리오로 진입·손절·익절 제시.
- **호가 진입 도구** (호가 탭): ±0.25/0.5/1/2% 깊이 불균형, 불균형 추이, 벽 유지 시간, 가격이 닿기 전에 사라진 벽(허수 의심),
  $10K~$5M 시장가 슬리피지, 벽 기준 롱·숏 지정가 계획.
- **기관식 포트폴리오** (`quant/portfolio.py`, 퀀트 → 포트폴리오): 동일 비중·변동성 역가중·리스크 패리티·최소 분산·최대 샤프
  (학습 70% → 검증 30%, 공분산 수축, 비중 상한) + 효율적 투자선, 실제 위기(코로나·중국 규제·루나·FTX·엔캐리) 재현과 가상 충격
  스트레스 테스트(레버리지 청산 위험 표시), BTC 베타·모멘텀·변동성 팩터 노출과 유동성(거래대금 대비·정리 일수·슬리피지),
  성과 티어시트(샤프·소르티노·칼마·낙폭 기간·월별 수익률·코인/방향/시간대/요일별 손익).

### 모든 코인 · 모든 봉
전략은 BTC 1시간봉에 묶이지 않는다. 전략 화면의 '대상'에서 코인(한글·영문 이름 가능)과 봉(1분~월봉)을 바꾸면
그 조합으로 백테스트·자동 개선·페이퍼 봇이 돈다. `POST /api/strategy/scan` 은 같은 전략을 여러 코인 × 여러 봉
(최대 80개 조합)으로 병렬 백테스트해 수익률순으로 돌려주고, 화면에서 줄마다 보기·개선·봇 시작을 할 수 있다.
규칙 파서도 3분·2시간·6시간·12시간·3일·주봉·월봉을 이해한다.

### 모의 포지션 · 지지저항
- 모의 진입 후 차트에 진입가(실시간 수익률)·손절·익절·강제청산 선이 뜬다. 손절·익절 선은 **마우스로 끌어서** 옮기거나
  포지션 표에서 가격을 입력해 바꾼다(현재가·강제청산가를 넘는 잘못된 값은 거부).
- **자동 지지·저항**: 스윙 고점·저점을 0.6 ATR 안쪽끼리 묶어 여러 번 부딪힌 가격대를 구간으로 표시(터치 횟수·최근성으로 강도 계산),
  최근 두 고점/저점으로 하락 저항 추세선·상승 지지 추세선을 그린다. 시나리오의 목표·손절 레벨에도 같은 구간을 쓴다.

### 고래맵
- **고래 체결**: 기준 금액(BTC $50만, ETH $25만, 기타 $10만) 이상 체결을 버블로 표시. 바이낸스는 과거 체결을 많이 주지 않아서
  **프로그램이 켜져 있는 동안 보고 있는 코인의 체결을 계속 모은다**(처음 켠 직후에는 적게 보임).
- **호가 벽**: 현재가 ±5% 안에서 주변보다 물량이 크게 쌓인 가격대를 차트 오른쪽 막대로 표시.

### 전략 대화 · 자동 개선
- 첫 문장으로 전략을 만들고, 이후 "손절 3%로", "RSI 조건 빼줘", "MACD 도 추가", "손실이 많아" 처럼 말하면 수정 → 즉시 백테스트 → 전·후 비교.
  Claude 키가 있으면 Claude 가 대화 맥락과 직전 성과를 보고 고친다. 결과가 크게 나빠지면 경고하고, 버전 기록에서 되돌릴 수 있다.
- **복기**: 모든 거래에 진입 당시 시장 상태(EMA200 추세·ADX·RSI·변동성·이격·거래량·슈퍼트렌드·펀딩)를 붙여
  익절은 "왜 됐는지", 손실은 "무엇이 문제였는지" 문장으로 남기고 원인·공통점을 집계한다.
- **자동 개선**: 손실 원인을 막는 필터와 손절·익절 조정을 후보로 만들어, 데이터 앞 70%(학습)에서 좋아지고
  **뒤 30%(검증, 개선에 쓰지 않은 구간)에서도 나빠지지 않는 것만** 채택한다(`backend/app/improve.py`).
  페이퍼 봇에서 '자동 개선'을 켜면 새 거래 N건마다 스스로 복기·개선하고 변경 이력을 남긴다.
  과거 데이터로 검증했다고 미래 수익이 보장되지는 않는다.

### 청산맵
CoinGlass 키가 있으면 CoinGlass 데이터를 쓴다. 없으면 미결제약정 증가분을 신규 포지션으로 보고,
레버리지 10/25/50/100배 분포의 청산가에 쌓은 뒤 가격이 지나가면 지우는 방식으로 추정한다
(`backend/app/liquidation.py`). OI 데이터도 없으면 거래대금으로 대체하며, 이때는 상대 강도만 의미가 있다.

### 시장 판단 · 시나리오
EMA 배열·EMA50 기울기·슈퍼트렌드·고점/저점 구조·MACD로 점수(-100~+100)를 매기고, ADX와 효율비(순이동÷총이동)로
추세장/횡보장을 가른다. 스윙 고저점·박스 상하단·EMA·청산 구간을 레벨로 써서 롱/숏/박스 시나리오를 만들고,
목표가는 최소 1R 이상 떨어진 레벨로 잡는다 (`backend/app/analysis.py`). Claude 키가 있으면 "AI 코멘트"로 브리핑을 받을 수 있다.

## 실행

### 파이썬 없이 실행 (추천)

1. [Releases → desktop-latest](https://github.com/g1792091-boop/crypto-bot-research/releases/tag/desktop-latest)에서 운영체제에 맞는 zip을 받는다.
   - Windows: `CoinFuturesTerminal-windows-x64.zip`
   - Mac (M1/M2/M3 등 Apple Silicon): `CoinFuturesTerminal-macos-arm64.zip`
2. 압축을 풀고 `CoinFuturesTerminal.exe`를 더블클릭한다 (Mac은 우클릭 → 열기).
   Windows에서 "PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누른다.
3. 브라우저가 자동으로 열린다. API 키는 같은 폴더의 `settings.txt`를 메모장으로 열어 넣는다.

이 실행 파일은 GitHub Actions(`.github/workflows/build-desktop.yml`)가 코드를 푸시할 때마다 자동으로 빌드한다.
직접 빌드하려면 `pip install -r backend/requirements.txt pyinstaller && python packaging/build.py`를 실행한다.

### 파이썬으로 실행 (개발용)

```bash
cd backend
pip install -r requirements.txt

# 선택: 키가 있으면 기능이 확장된다
export GEMINI_API_KEY=...             # 무료: 자연어 변환·에이전트 팀을 Gemini로 (https://aistudio.google.com/apikey)
export ANTHROPIC_API_KEY=sk-ant-...   # 또는 Claude (둘 다 있으면 Claude, 없으면 규칙 기반)
export COINGLASS_API_KEY=...          # OI, 펀딩, 롱숏, 청산을 CoinGlass로 (없으면 바이낸스 공개 API)

uvicorn app.main:app --reload --port 8000
# → http://localhost:8000
```

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude 사용 여부 |
| `CLAUDE_MODEL` | `claude-opus-5-5` | 전략 변환과 에이전트에 쓰는 모델 |
| `GEMINI_API_KEY` | – | Gemini 사용 (무료 등급 키 가능) |
| `GEMINI_MODEL` | 자동 | 비우면 키로 쓸 수 있는 최신 Flash 모델을 목록 API로 골라 쓴다. 한도에 걸리면 다른 Flash/Flash-Lite 로 넘어감 |
| `GEMINI_RPM` | `10` | 분당 최대 요청 수 (무료 등급 한도에 맞춰 호출 간격 조절) |
| `LLM_PROVIDER` | `auto` | `auto`(Claude 키 우선) / `claude` / `gemini` |
| `COINGLASS_API_KEY` | – | CoinGlass v4 API 키 (Hobbyist 플랜 이상) |
| `DATA_SOURCE` | `auto` | `auto`(바이낸스 → 실패 시 합성), `binance`, `synthetic`(오프라인 데모) |
| `PAPER_POLL_SECONDS` | `15` | 페이퍼 봇과 계좌 폴링 주기 |
| `STATE_DIR` | `backend/state` | 페이퍼 계좌와 봇 상태 저장 위치 |

> 바이낸스 선물 API는 미국 IP에서 차단된다. 서버는 아시아 리전에 두는 것이 좋다.

테스트:

```bash
cd backend && python -m pytest -q
```

## 자연어 → 전략 예시

```
BTC 1시간봉 EMA 20/50 골든크로스 롱, 데드크로스 숏. RSI 70 이상이면 롱 제외. 손절 2% 익절 4%, 레버리지 5배
이더 15분봉 RSI 30 이하에서 돌파하면 롱, 10배, 손절 1.5 익절 3
솔라나 4시간 슈퍼트렌드 전환 + 거래량 2배, 트레일링 3%, 롱만
볼린저 하단 이탈 + MACD 골든크로스 + 펀딩비 음수일 때 롱
```

API 키가 없으면 규칙 파서가 위와 같은 흔한 패턴만 이해한다. 키가 있으면 Claude 또는 Gemini 가 구조화 출력(JSON 스키마)으로 임의의 설명을 변환하고, 검증 오류가 나면 한 번 더 고친다.
AI 호출이 실패하면(무료 한도 초과, 키 오류 등) 전략 변환·대화 수정·에이전트 팀은 규칙 기반으로 대신 처리하고 화면에 이유를 표시한다.

## 전략 JSON (DSL)

```json
{
  "name": "EMA 크로스 + RSI 필터", "symbol": "BTCUSDT", "interval": "1h",
  "indicators": [
    {"id": "fast", "type": "ema", "length": 20},
    {"id": "slow", "type": "ema", "length": 50},
    {"id": "rsi",  "type": "rsi", "length": 14},
    {"id": "m",    "type": "macd"}
  ],
  "long_entry":  {"logic": "all", "conditions": [
    {"left": "fast", "op": "crosses_above", "right": "slow"},
    {"left": "rsi",  "op": "<", "right": "70"},
    {"left": "m.hist", "op": "rising", "right": "2"},
    {"left": "funding", "op": "<", "right": "0.01"}
  ]},
  "short_entry": {"logic": "all", "conditions": [{"left": "fast", "op": "crosses_below", "right": "slow"}]},
  "long_exit": null, "short_exit": null,
  "risk": {"leverage": 5, "position_pct": 20, "stop_loss_pct": 2, "take_profit_pct": 4,
           "atr_stop_mult": null, "trailing_stop_pct": null, "fee_pct": 0.04, "allow_reverse": true}
}
```

- 지표: `sma ema rsi macd bb atr stoch supertrend adx cci vwap obv highest lowest volume_sma`
  (TradingView Pine `ta.*`와 같은 공식)
- 피연산자: 가격(`close`…), 지표 `id`, 다중 출력 `id.출력`(`macd.hist`, `bb.lower`, `st.trend`),
  파생 데이터(`funding`, `oi`, `oi_change_pct`, `long_short`), 과거값 `close[1]`, 배수 `vol_ma*2`, 숫자
- 연산자: `> < >= <= crosses_above crosses_below rising falling`

## 구조

```
backend/app/
  main.py            FastAPI 라우트 + 정적 파일
  analysis.py        시장 판단(롱/숏/횡보), 멀티 타임프레임, 레벨, 시나리오
  improve.py         거래 복기(학습 노트) · 자동 개선(학습/검증 분리)
  orderflow.py       호가창 · 호가 벽 · 고래 체결 수집기
  data/exchanges.py  거래소별 시세 · 김치 프리미엄
  data/sentiment.py  공포·탐욕 · 코인베이스 프리미엄 · CoinGlass 지수
  liquidation.py     청산맵 (CoinGlass / OI 기반 추정)
  data/binance.py    바이낸스 USDⓈ-M 공개 API (캔들, 펀딩, OI, 롱숏, 24h)
  data/coinglass.py  CoinGlass v4 어댑터
  data/market.py     소스 통합, 폴백, 캐시, 도미넌스, 히트맵
  data/news.py       RSS 뉴스, 경제지표 캘린더
  data/synthetic.py  오프라인 데모용 결정론적 캔들
  indicators.py      Pine 호환 지표 엔진
  strategy.py        전략 DSL(pydantic), 신호 계산, 검증
  engine.py          선물 시뮬레이터 (레버리지, 청산, 수수료, 펀딩, 손절·익절·추적)
  backtest.py        백테스트와 지표 산출
  paper.py           페이퍼 봇, 수동 페이퍼 계좌, 백그라운드 루프
  nl_strategy.py     자연어 → 전략 (Claude 구조화 출력 / 규칙 파서)
  agents.py          AI 에이전트 팀
  llm.py             AI 래퍼: Claude(구조화 출력, 서버측 폴백) 또는 Gemini 로 분기
  gemini.py          Gemini REST 호출 (모델 자동 선택, 분당 한도 조절, 429 시 대기·다른 모델, JSON 스키마 검증·재요청)
frontend/            바닐라 JS 모듈 (js/: core, chart, ind, trade, alerts, lab, agents, market), lightweight-charts 5.2.1 vendored (Apache-2.0)
docs/ANALYSIS.md     레퍼런스 사이트 분석, 외부 서비스 제약, 로드맵
```
