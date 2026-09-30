# 진입 수치 · 파라미터 · 지지저항 연구 — 결과

사전 등록: `PREREG_ENTRY.md` (해시 `PREREG_ENTRY.sha256`). A·B·C 결과와 후보 목록은 각 부분이 끝나면 이 문서에 적습니다. 지금은 A만 끝났고, B·C 결과는 나중에 적습니다.

- **A (지지·저항) 결과:** [`RESULTS_ENTRY_A.md`](RESULTS_ENTRY_A.md). 후보 2개(N17_KC_RSI 5분봉 P1, N04_ST_KLINGER 5분봉 P1)이며, 둘 다 "시장 전체의 성질"로 표시했습니다.

## 해석 주의 · 사전 등록과 다르게 처리한 것

### A — 지지·저항
- **DOGE 결합 오류를 고치고 다시 돌렸습니다.** 첫 실행은 DOGE = DOGE_L − DOGE_S로 합쳤습니다. 그런데 잠긴 `compute_signals`가 DOGE_S를 숏 봉에서 이미 −1로 저장하므로, DOGE 숏 신호가 모두 **롱**으로 들어갔습니다. 같은 오류가 실시간 봇(`paperbot/sigservice.py`)과 백테스트 캐시에도 있었습니다.
  - 이 연구의 검증 단계(verifier)에서 찾았습니다. paper 거래를 시작하기 전에 `paperbot.sigservice.doge_join`(빼기 대신 더하기)으로 실시간 봇과 모든 캐시를 고쳤습니다. 이 오류로 거래한 paper 계좌는 없습니다.
  - `analysis_sr.py`는 계산을 바꾸지 않고 다시 돌렸습니다. 바뀐 것은 DOGE 검정 8개(모두 여전히 BH 탈락)와, BH 순위가 바뀐 데 따른 다른 검정의 q값입니다. 후보 목록과 첫 줄 숫자(145칸, 검정 290개, ① 표본 부족 55개, 단계별 2 / 2 / 2 / 2)는 그대로입니다.
  - 데이터 오류를 고친 것이며, 결과를 보고 고른 것이 아닙니다. 첫 실행 출력은 `out/before_doge_fix/`에 있습니다. 자세한 내용은 `RESULTS_ENTRY_A.md` 5장 12번에 있습니다.
- A의 나머지 모호한 점과 처리 방법: `out/run_meta.json`의 `ambiguities`, `RESULTS_ENTRY_A.md` 5장.

### B·C
- 결과는 나중에 적습니다.
- B·C의 DOGE 정의(`param_defs/DOGE.py`, `strength_defs/DOGE.py`)도 고친 결합(롱 규칙은 롱, 숏 규칙은 숏)에 맞췄습니다(`JOIN_AS_CACHED = False`).
