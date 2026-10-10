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
| `combo_watch.py WORKROOT` | 관찰 후보 38개 계좌(`watch_sel.json`): 겹침·상관, 지금 크기와 1/4 크기 계좌 | → `combo_sum.py` → `combo_sum.json` |
| `strat_report.py WORKROOT` | 매매법 80개 × 봉 4개: 지금 숫자와 커스텀값 1등의 기간별·장세별·코인별 성적, 계좌 | → `strat_md.py` → `../STRATEGIES_KO.md` (계산 파일은 딥시크 돈 숫자가 들어 있어 올리지 않음) |
| `strat_deep.py WORKROOT` | 연도별 성적, 계좌 위험(연속 손실·최악의 달·회복 기간), 1/4 크기 계좌, 같은 자리 반대 방향 (지금 숫자와 커스텀값 1등) | 계산 파일은 딥시크 돈 숫자가 있어 올리지 않음 |
| `gross_all.py WORKROOT` | 315칸 지금 숫자, 수수료 0 | 계산 파일은 올리지 않음 |
| `landscape.py RESULTS OUT` | 커스텀값 지형(모든 커스텀값, 지금 청산)과 청산 84가지 순위 | 딥시크는 결과 파일에 돈 숫자가 없어 빈칸 |
| `strat_eval.py ANA RESULTS OUT` | 위 계산을 모아 매매법별 평가와 등급 → `../STRATEGY_EVAL_KO.md` (`eval_notes_ko.json`의 해석 포함) | |

