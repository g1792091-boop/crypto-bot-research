# GH Coin

코인 전문 AI 에이전트 회사. GH Nano(`../nuri-ai/`)의 엔진(AI 연결·지표 165종·커스텀 수식·백테스트·ML/딥러닝·데모·실거래·차트 터미널·자체 코드 수정)을 그대로 쓰고, 조직과 업무만 코인에 맞게 따로 둔다. 저장소(회의 기록 `coin:log`, 데모 장부 `coin:paper`, 과제·노트 `coin*`, 결과물 `coindoc:`)는 GH Nano 와 섞이지 않는다. AI 키 설정은 같은 주소에서 실행하면 GH Nano 와 공유한다.

- `coin-org.js` 24개 팀 × (팀장 1 + 팀원 10) + CEO실, 질문 단어 → 담당 팀장, 자동 회의 안건, 관찰 대상, 수다 상대
- `coin-office.js` 엔진 (`../nuri-ai/office.js` 에서 갈라짐): 일반·커스텀 두 라인(`LANES`) 매매법 개발 → 백테스트 → 데모, 관문 심사(`promoteJob`), 분석 팀 업무(`indJob`·`trendJob`·`entryJob`·`srJob`·`tpslJob`·`patternJob`·`situJob`·`coinJob`), `pipeline()`
- `combo.js` 실시간 종합 지표 타점 엔진: 차트 터미널 지표 136종 → 지표별 상승·하락 표(`voteOf`) · 장세 필터 · 레벨 묶음(`clusterLevels`) → 시간대 점수(`analyzeTF`) → 타점(`planOf`) · 기록장 채점(`gradeCall`). `coin-office.js`의 `startCombo`(60초 루프)·`comboJob`·`comboBoard` 가 쓴다
- `coin-ui.js` 픽셀 본부 화면 (`../nuri-ai/office-ui.js` 에서 갈라짐): 6열 배치, 분석 표 카드, 실거래 후보 카드, #⚡실시간 타점판·#파이프라인 탭, 타점판 크게 보기
- `coin-app.js` 시작·AI 연결 창·학습 데이터 내려받기, `index.html` 코드 수정 안전장치 포함

실거래는 코드가 판정한 관문(14일·20거래·손익비 1.2·수익+·낙폭<25%)을 통과한 뒤에도 사용자가 실거래 화면에서 직접 켜고 연결해야 하며, `live.js`의 한도·승인 안에서만 주문한다. GH Nano 안에서는 [🪙 코인 본부] 버튼으로 같은 화면이 열린다(iframe, 같은 키 공유).
