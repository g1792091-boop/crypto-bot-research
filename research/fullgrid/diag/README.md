# 결과를 본 뒤의 참고용 분석

`ANALYSIS_KO.md`의 5-3 ~ 5-5에 쓴 숫자를 만든 스크립트입니다. 사전 등록 밖이라 통과·탈락을 바꾸지 않습니다. 규칙봇(core)
숫자만 다루며 딥시크 돈 숫자는 없습니다(D11).

WORKROOT에는 `fg1m/`(실행과 같은 1분봉), `fgwork/`(결과표, `frames/`), `fgresults/<결과 브랜치>/`가 있어야 합니다.

| 스크립트 | 하는 일 | 요약 파일 |
|---|---|---|
| `gross_cost.py WORKROOT 4h,1h` | 지금 숫자, 비용 0배와 1배 | `gross_4h_1h.json` → `gross_sum.py` → `gross_sum.json` |
| `side_skill.py WORKROOT` | 같은 진입 자리, 고른 방향 vs 반대 방향 | `side_skill.json` → `side_sum.py` |
| `uncond.py WORKROOT` | 매매법 없이 모든 봉, 롱·숏 | `uncond.json` |
| `regime_explore.py WORKROOT` | 장세별 강점이 다음 기간에도 유지되나 | `regime_explore.json` → `regime_sum.py` |
| `top_picks.py WORKROOT` | 시험 기간 1~3등의 승률·손익비·계좌 결과·반대 방향 | `top_picks.json` |
