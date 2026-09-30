# 코인 선물 터미널 (crypto-bot-research)

코인 무기한 선물용 분석·백테스트·페이퍼 트레이딩 터미널이다.
**말로 설명한 진입 기준**을 전략 JSON으로 바꾼 뒤 스스로 백테스트하고 페이퍼 봇으로 돌린다.
사용자는 TradingView 차트에서 보조지표를 조합하며 직접 모의 매매할 수 있다.
AI 에이전트 팀(기술, 파생, 뉴스·매크로 분석가 → 리스크 매니저 → 헤드 트레이더)이 시장을 분석하고 결정을 내린다.

레퍼런스 사이트(Astral, HelloQuant) 분석과 외부 서비스 제약은 [docs/ANALYSIS.md](docs/ANALYSIS.md)에 정리했다.

> ⚠️ 투자 조언이 아니다. 실거래 주문 기능은 없고 모든 매매는 모의(페이퍼)다.

## 화면 구성

| 탭 | 기능 |
|---|---|
| **트레이딩** | TradingView 차트(지표 칩으로 조합), OI·펀딩비·롱숏비율 패널(CoinGlass 또는 바이낸스), 현재가·마크가·다음 펀딩, 수동 페이퍼 주문(레버리지, 손절·익절), 계좌·포지션 |
| **전략 랩 · 백테스트** | 자연어 → 전략 변환, 지표·조건·리스크 빌더, JSON 편집, 백테스트(수익률, MDD, 샤프, 승률, PF, 강제청산, 수수료, 펀딩), 진입·청산 마커 차트, 자본 곡선, 거래 내역 |
| **페이퍼 봇** | 전략을 실시간 캔들에 붙인 자동 모의매매 봇 목록, 로그, 자본 곡선, 일시정지·청산·삭제 |
| **AI 에이전트 팀** | 3명의 분석가가 병렬로 분석 → 리스크 한도 → 최종 결정(진입, 손절, 익절, 레버리지) → 페이퍼 주문 버튼 |
| **마켓 · 뉴스** | BTC·ETH·스테이블 도미넌스, 선물 24h 히트맵, TradingView 코인 히트맵, RSS 뉴스, 뉴스 타임라인, 경제지표 일정, BTC.D/USDT.D |

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
frontend/            바닐라 JS (빌드 불필요), lightweight-charts 4.2.3 vendored (Apache-2.0)
docs/ANALYSIS.md     레퍼런스 사이트 분석, 외부 서비스 제약, 로드맵
```
