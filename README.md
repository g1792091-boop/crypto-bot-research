# crypto-bot-research

코인 선물 자동매매 전략 연구 저장소 (봇 코드 아님 — 백테스트·검증 전용).

- **[ANALYSIS_KO.md](ANALYSIS_KO.md)** — 1단계 인수인계 검토 결과 (먼저 읽을 것)
- [HANDOFF_FOR_CLAUDE_CODE.md](HANDOFF_FOR_CLAUDE_CODE.md) — 1단계 인수인계 원본
- `bt/` — 백테스트 엔진·전략 포팅 (1단계 원본 그대로)
- `data/` — Astral OHLCV (현물 집계가). `data/fresh/`는 이번 검토에서 추가로 받은 데이터 (.csv.gz)
- `results/` — 1단계 결과표
- `analysis/` — 검토 근거 (B안 사전 등록 표본 외 검정, 감사 메모, 추가 검정 스크립트)

재현: `pip install "pandas>=2,<3" numpy && cd bt && python3 run.py --window IS --tag all5 && python3 analyze.py --window IS --tag all5`

- **[DOGE_STRATEGY_ANALYSIS_KO.md](DOGE_STRATEGY_ANALYSIS_KO.md)** — 친구 도지코인 5분 매매법(Astral #5864) 검토 결과
