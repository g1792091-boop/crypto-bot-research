# vendor/ — 외부 저장소에서 실제로 가져온 원본 코드

여기 있는 파일은 **GitHub 저장소의 실제 소스를 받아 그대로 넣은 것**이다(수정하지 않음). 각 폴더의 `LICENSE` 를 함께 보관한다.
GH Coin 은 브라우저(빌드 없는 바닐라 JS) 앱이라 파이썬/React 파일은 그대로 실행되지 않으므로, 실행되는 형태로 **충실히 이식한 모듈**을 함께 둔다(같은 공식·반올림·검증 규칙, 출력 일치를 테스트로 확인).

| 원본(이 폴더) | 라이선스 | 실행되는 이식본 | 상태 |
|---|---|---|---|
| `ai-trader-team/trading_rigor.py` | MIT | `../lib/rigor.js` | 이식(출력 일치 확인) |
| `ai-trader-team/backtest.py` | MIT | `../lib/attbacktest.js` | 이식(출력 일치 확인) |
| `ai-trader-team/cli_utils.py` | MIT | — | 원본 보관(참조용) |
| `anythingllm-embed/useSessionId.js` | MIT | `../coinai.js` 세션/기록 로직 | React 제거해 이식 |
| `anythingllm-embed/constants.js` | MIT | **`../coinai.js` 에서 그대로 import 해 사용** | 원본 그대로 실행 |
| `anythingllm-embed/date.js` | MIT | `../coinai.js` 시각 표시 | i18n 의존 제거해 이식 |
| `agency-agents-ko/finance-investment-researcher.md` | MIT | `../coinai.js` 지식(투자 원칙) | 원칙 이식 |

왜 원본을 "통째로 실행"하지 못하나: Dify·Flowise·continue·TEN·AnythingLLM 본체는 Python/Node 서버 또는 빌드가 필요한 React/Electron 앱이라, 빌드 과정 없는 단일 브라우저 앱에 소스를 그대로 넣어 실행할 수 없다. 그래서 (1) 순수 로직 파일은 원본을 보관하고 실행본으로 이식하고, (2) 의존성 없는 순수 파일(`constants.js`)은 원본을 그대로 import 해 쓴다.
