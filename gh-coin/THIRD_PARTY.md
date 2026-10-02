# 참고한 오픈소스 (GH Coin)

아래 저장소의 **아이디어·규칙·공식**을 읽고 GH Coin 에 맞게 새로 작성했다. 코드를 복사하지 않았다.
GPL·LGPL 저장소와 라이선스 표시가 없는 저장소는 특히 규칙만 참고했다.

| 저장소 | 라이선스 | 들여온 것 |
|---|---|---|
| freqtrade/freqtrade | GPL-3.0 | ROI 표·추적손절·보호장치·하이퍼옵트 손실함수 공식 |
| mementum/backtrader | GPL-3.0 | SQN·VWR·Returns·DrawDown·TradeAnalyzer 공식 |
| nautechsystems/nautilus_trader | LGPL-3.0 | 주문 전 점검 순서·거래 상태·TWAP·고정위험 사이저 규칙 |
| vnpy/vnpy | MIT | 리스크 매니저 규칙·아이스버그·Alpha158 팩터 정의 |
| ccxt/ccxt | MIT | 통일 API 개념·거래소 공개 엔드포인트·단위 정규화 |
| openbq-org/OpenBB (OpenBB ODP) | Apache-2.0 | 공급원 구조·무료 공개 데이터 주소 |
| goldmansachs/gs-quant | Apache-2.0 | 시계열 위험 지표 정의·시나리오 충격 개념 |
| goldmansachs/jdmn | Apache-2.0 | DMN 결정표 단항 검사·적중 정책 |
| goldmansachs/legend-engine · legend-studio · legend-sdlc, finos/legend | Apache-2.0 | 모델 제약·SDLC(작업공간→검토→버전) 개념 |
| goldmansachs/obevo | Apache-2.0 | 변경 기록·체크섬·롤백 개념 |
| goldmansachs/reladomo | Apache-2.0 | 이중 시간 밀스토닝 개념 |
| TauricResearch/TradingAgents | Apache-2.0 | 다중 에이전트 투자위원회 절차·교훈 기억 |
| HKUDS/Vibe-Trading | MIT | 검증 관문·순열 검정·펀딩 상태 규칙 |
| BennyThadikaran/stock-pattern | GPL-3.0 | 패턴 감지 규칙·허용오차 |
| zeta-zetra/chart_patterns | (표시 없음) | 회귀선 패턴 분류 아이디어 |
| BitOracle-bitoracle/bitoracle-ai-server | (표시 없음) | 확률 밴드 규칙 아이디어 |
| iliaal/tradingview-mcp | MIT | 차트 조회 개념 (기술 요약 규칙은 MIT python-tradingview-ta) |
| johnmackintosh/runcharter | GPL-3.0 | 런 차트 이동 규칙 |
| jh941213/my-cc-harness | MIT | 독립 QA 채점·검증 절차 |
| RanitManik/gemini-clone | MIT | 추천 질문·최근 질문 UI 아이디어 |

## 선물 자동매매봇 (추가)
아래 트레이딩 봇의 **전략·리스크 규칙**만 읽어 우리 전략 JSON / 백테스트 시뮬레이터로 다시 작성했다(코드 복사 없음).

| 저장소 | 들여온 것 |
|---|---|
| enarjord/passivbot (Unlicense) | 그리드·DCA(물타기) 방식과 지갑 노출·물타기 한도 개념 → `lib/botsim.js` (연구용 백테스트) |
| jesse-ai/jesse (MIT) | 전략 클래스·백테스트 구조 → 추세추종·평균회귀 봇 전략 |
| Drakkar-Software/OctoBot (GPL-3.0/LGPL) | 트레이딩 모드(그리드·DCA·돌파) → 돌파·슈퍼트렌드 봇 |
| conor19w/Binance-Futures-Trading-Bot (라이선스 없음) | 선물 TA 봇 진입·손절·레버리지 → 봇 전략 조건·한도 |
| Erfaniaa/crypto-trading-strategy-backtester (GPL-3.0) | 교차 전략 백테스트 참고 |

## 자체 AI·에이전트 (아이디어만, 코드 복사 없음)
| 저장소 | 들여온 것 |
|---|---|
| TLSRUF/ai-trader-team (MIT) | **실제 이식**: `tools/trading_rigor.py` → `lib/rigor.js`(포지션 사이징·손익비·R-멀티플·켈리·포트폴리오 히트·상관계수, 같은 공식·반올림). 합의 방식은 자체 AI 확신도에도 반영 |
| jnMetaCode/agency-agents-ko (MIT) | **실제 이식**: finance/투자 리서처 핵심 원칙 → 코인 AI 봇 지식(APP_KB) + 자체 AI 데스크 역할 분담 |
| anthropics/claude-cookbooks | 앙상블·LLM-판정 패턴, '우위(edge)'로 신뢰 조정 |
| anthropics/financial-services | 리스크·확신도 프레이밍(단정 금지·참고값·확신도 상한 95) |
| anthropics/claude-code | 에이전트-도구·코드 수정 검토 패턴(기존 selfdev 참고) |
| continuedev/continue (Apache-2.0) | 여러 모델/소스를 한 인터페이스로 합치는 발상 |
| ten-builder/ten-builder (Apache-2.0) | 조합형 확장 그래프 개념(신호를 부품처럼 합성) — 음성·실시간 인프라는 범위 밖 |
| anthropics/uplifting-biomolecular-modeling | **해당 없음** — 생체분자 모델링이라 코인 트레이딩과 무관, 적용하지 않음 |

> 자체 AI(`lib/selfai.js`)는 **외부 LLM 키 없이** 이 앱 안에서 도는 앙상블이다: 기술 평점(트레이딩뷰식)·멀티 시간대 종합 점수·ML 확률(walk-forward)·알파 팩터를 가중 합성해 방향과 확신도(0~95)를 낸다. **판단만 하고 주문은 내지 않는다** — 실제 주문은 그대로 `../nuri-ai/live.js`(한도·승인·긴급정지)만 낸다.

## 코인 AI 봇(자체 RAG) (아이디어만, 코드 복사 없음)
| 저장소 | 들여온 것 |
|---|---|
| langgenius/dify · dify-plugins | '내 지식으로 답하기(RAG)' · 지식 베이스 · 모델 제공자 추상화 개념 |
| FlowiseAI/Flowise · FlowiseChatEmbed · FlowiseEmbedReact · FlowiseDocs | 신호·체인 조합 + '어디에나 띄우는 채팅 위젯(embed)' |
| Mintplex-Labs/anything-llm · -embed · -extension · -mobile · -docs (MIT) | **실제 이식**: anythingllm-embed `useSessionId.js`·`useChatHistory` 세션/대화기록 보존 방식 → 코인 AI 봇. 완전 자체(프라이빗) RAG·외부 키 없이 동작 구조도 반영 |
| probot/probot · template · create-probot-app · probot.github.io | **해당 없음** — GitHub App 프레임워크라 코인 앱과 무관, 적용하지 않음 |

> 코인 AI 봇(`coinai.js` + `lib/ragstore.js`)은 **외부 서비스·벡터DB 없이** 브라우저/Node 안에서 도는 가벼운 RAG(TF-IDF + 코사인, 한국어 2-그램)다. 이 앱이 아는 것(전략·백테스트·분석 노트·자체 AI 판단·앱 설명)을 지식으로 모아, **외부 AI 키가 없으면 추출 답변(완전 자체)**, 키가 있으면 그 지식에 **근거한** LLM 답변을 한다. 설명·판단만 하고 **주문은 내지 않는다**.

## 멀티에이전트 설계 (ARTEX — 공격 기능 전부 제외, 코드 복사 없음)
`Autumn-27/ARTEX`(AGPL-3.0)는 **보안 공격(레드팀)용 자율 AI 도구**다. 그 **공격류 기능은 하나도 넣지 않았고**, repo를 vendor에 두거나 코드를 복사하지도 않았다. 가져온 것은 **범용 멀티에이전트 설계(아이디어)뿐**이다:
- **planner + 공유 todolist** → `lib/planner.js`: 상태(코인·전략·관문·경보·보드)를 보고 '지금 할 일 목록'을 우선순위로 만들고, 선행조건을 지키며 중복을 피해 다음 의도를 고른다.
- **worker** → `coin-office.js plannerJob`: 고른 의도를 **기존 트레이딩 job**(추세·종합타점·자체 AI·백테스트·자동개선 등)으로 실행한다.
- **공유 사실 보드 + 혈연 링크** → `lib/board.js`: 결과(발견·사실)를 한곳에 디듀프하며 쌓고, 어느 의도에서 나왔는지 기록한다.

쓰는 데이터·행동은 전부 '우리 앱이 이미 하던 트레이딩 리서치'뿐이고, 네트워크 공격류 요소는 전혀 없다.

## 만들지 않은 것 (의도적으로 제외)
사용자가 함께 요청했지만 다음은 안전·합법성 때문에 **만들지 않았다**:
- **남의 지갑을 여는 도구**: 다른 사람의 개인키·시드로 지갑을 찾아 여는 것은 절도라서 구현하지 않음.
- **앱 내장 채굴기 + 자동 송금**: 배포되는 실행 파일 안에 채굴 기능을 넣어 한 지갑으로 자동 송금하면, 받는 사람 PC에서 몰래 도는 악성 프로그램 형태가 되므로 넣지 않음. 본인 PC에서 합법 채굴 프로그램을 본인 지갑으로 직접 돌리는 것은 사용자 자유.
- **앱 자체 코인 지갑(실제 자금 보관)**: 개인키를 이 앱에 두는 것은 위험하고 위 흐름의 목적지라서 넣지 않음. 보관은 Rainbow 등 검증된 지갑 사용 권장.
