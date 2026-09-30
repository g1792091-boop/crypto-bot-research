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
lightweight-charts v5 로 직접 그리고, 보조지표 44종을 브라우저에서 계산한다(`frontend/js/ind.js`, Pine 과 같은 공식 —
백테스트 엔진과 수치가 일치하는지 테스트로 확인). 추세(EMA·SMA·WMA·HMA·VWMA·리본·슈퍼트렌드·파라볼릭 SAR·일목·VWAP·피봇),
변동성(볼린저·켈트너·돈치안·엔벨로프·ATR·밴드폭·초피니스), 오실레이터(RSI·스토캐스틱 RSI·스토캐스틱·MACD·CCI·윌리엄스 %R·MFI·ADX·
스퀴즈 모멘텀·웨이브트렌드·어썸·ROC·TRIX·아룬), 거래량(거래량·OBV·CMF·CVD·델타), 파생(OI·OI 변화·펀딩·롱숏·테이커·청산·코인베이스 프리미엄).

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
export ANTHROPIC_API_KEY=sk-ant-...   # 자연어 변환과 에이전트 팀을 Claude로 (없으면 규칙 기반)
export COINGLASS_API_KEY=...          # OI, 펀딩, 롱숏, 청산을 CoinGlass로 (없으면 바이낸스 공개 API)

uvicorn app.main:app --reload --port 8000
# → http://localhost:8000
```

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude 사용 여부 |
| `CLAUDE_MODEL` | `claude-opus-5-5` | 전략 변환과 에이전트에 쓰는 모델 |
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

API 키가 없으면 규칙 파서가 위와 같은 흔한 패턴만 이해한다. 키가 있으면 Claude가 구조화 출력(JSON 스키마)으로 임의의 설명을 변환하고, 검증 오류가 나면 한 번 더 고친다.

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
  llm.py             Claude API 래퍼 (구조화 출력, 서버측 폴백)
frontend/            바닐라 JS 모듈 (js/: core, chart, ind, trade, alerts, lab, agents, market), lightweight-charts 5.2.1 vendored (Apache-2.0)
docs/ANALYSIS.md     레퍼런스 사이트 분석, 외부 서비스 제약, 로드맵
```
