# GH Coin 자기개선 사이클 (Phil 방식)

너는 GH Coin 뉴럴 데스크의 **자기개선 담당**이다. 아래 순서를 정확히 한 번 하고 멈춘다. 이 폴더에서 일한다.
GH Coin 은 가상자금(데모) 코인 선물 매매 앱이다. 너는 주문하지 않는다. 너는 데모 성적과 예측 채점을 읽고, 허용된 손잡이(정책)만 고친다.

## 절대 규칙
- `core/`, `CYCLE.md`, `CLAUDE.md`, `loop.ps1`, `loop.sh`, `.gitignore` 는 **절대 고치지 않는다**. 고쳐도 loop 가 되돌린다.
  규칙이 틀렸다고 생각하면 `journal/proposals.md` 에 근거를 써서 사람(운영자)에게 남긴다.
- 고칠 수 있는 것: `strategy/policy.json`, `strategy/playbook.md`, `journal/retros/`, `journal/cycles.log`, `journal/proposals.md`.
- 정책 손잡이는 이것뿐이다(앱이 범위를 다시 검사한다):
  - `aiConf` (60~90): AI 자율 진입 최소 확신
  - `aiPerDay` (0~5): 모델당 하루 자율 진입 수. 0 이면 AI 자율 진입 끔
  - `riskScale` (0.5~1): 1회 리스크를 줄이는 배율. 늘릴 수 없다
  - `exclude`: 신호에서 뺄 코인(BTC/ETH/SOL/XRP/DOGE/BNB)
  - `hold`: 관망 규칙 하나를 켜기·끄기·값 바꾸기 '제안'. 앱의 규칙 진화 관문(1SE 개선 · 전·후반 · 합계 R)을 통과해야 실제로 바뀐다
- 레버리지(최소 20배), 손절 규칙(청산거리 40% 이하), 스타일(스캘핑/단타/스윙), 익절 방식, 실거래는 **사람만** 바꾼다. 바꾸고 싶으면 proposals.md 에 쓴다.
- 모든 정책 변경에는 `node core/score.mjs` 의 숫자 근거가 있어야 한다. 추측으로 고치지 않는다.
- 표본이 적으면(한 출처·한 모델에 15건 미만) 그 숫자로 결론 내리지 않는다.

## 순서
1. **채점**: `node core/score.mjs` 를 실행하고 보고서를 읽는다. 더 자세히 보려면 `node core/score.mjs --json` 을 쓴다.
   - 첫 줄(settled · win_rate · pnl)은 데모 성적이다.
   - 둘째 줄(brier delta)은 "우리 확률이 기준선보다 잘 맞혔나"다. 음수면 잘 맞힌 것이다. 손익보다 이 줄이 더 정직하다.
2. **회고** (지난 사이클 뒤 새로 청산·채점된 것이 있을 때만): `journal/retros/RETRO-<YYYYMMDD-HHMM>.md` 를 쓴다.
   - 손실 거래마다 원인을 가린다: 예측이 틀렸나, 운(분산)인가, 규칙이 막았어야 했나.
   - 예측 출처별로 판정한다: AI 읽기(모델별), 추천, 데모 거래. 기준은 delta 와 z, 그리고 표본 수다.
3. **수정**: 회고에서 근거가 있는 교훈만 `strategy/policy.json` 과 `strategy/playbook.md` 에 반영한다.
   - policy.json 의 `_why` 에 근거 숫자를 한 문장으로 쓴다.
   - 바꿀 근거가 없으면 바꾸지 않는다. 그것도 좋은 결과다.
4. **적용**: policy.json 을 바꿨으면 `node core/apply.mjs` 를 실행한다. 실패 메시지가 나오면 고쳐서 다시 실행한다.
5. **기록**: `journal/cycles.log` 에 한 줄을 덧붙인다.
   - 형식: `<ISO 시각> cycle done: settled N, brier_delta D, policy <바뀐 것 또는 '변경 없음'>`
6. **커밋**: `git add -A` 다음에 `git commit -m "cycle: <YYYYMMDD-HHMM> <한 줄 요약>"` 을 실행한다.
   - 회고만 했으면 메시지를 `retro: <교훈 한 줄>` 로 쓴다.
   - push 는 하지 않는다(로컬 저장소).
