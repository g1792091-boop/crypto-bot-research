# GH Nano · GH Coin 수정 패치

`ghnano-ghcoin-fixes.patch` 는 브랜치 `claude/eloquent-johnson-nnt7gh` (커밋 79440a4) 의 GH Nano(`nuri-ai/`) · GH Coin(`gh-coin/`) · 실행기(`launcher/`)에 대한 수정이다.
그 브랜치에서 `git apply patches/ghnano-ghcoin-fixes.patch` 후 `launcher/build.sh` 로 exe 를 다시 만든다.

고친 것
- 직원에게 AI 키가 안 들어가던 원인
  - GH Nano · GH Coin 창이 둘 다 열려 있으면 한쪽에서 넣은 키를 다른 쪽이 설정을 저장하면서 지워 버림 → 다른 창의 설정 변경을 실시간으로 받음 (`engine.js` storage 이벤트)
  - 채팅 두뇌를 '내 기기 AI'·Ollama 로 두면 API 로 일하는 직원도 짧은 지시문(스킬 없음, 답 1024 토큰)을 받음 → 실제로 부르는 모델 기준으로 계산 (`brainCtx`/`brainAnswerLen`)
  - 웹 버전에서는 NVIDIA 등에 연결이 안 되는데도 '연결됨'으로 보임 → 키 넣을 때와 사무실 상태 줄에 경고, 직원에게 AI 가 없으면 상태 줄에 경고
  - 예전 GHCoin.exe 가 안 꺼지면 새 실행기가 다른 포트(=다른 저장소)로 떠서 키가 사라진 것처럼 보임 → GHCoin.exe 도 강제 종료
- 결과물(사업계획서 등)을 어디서 보는지 모르던 문제
  - 결과물 창 맨 위에 실제 저장 경로 표시 (`/__nuri/officedir`)
  - 윈도우 '문서' 폴더가 OneDrive 로 옮겨진 PC 에서도 실제 문서 폴더 사용 (예전 위치에 폴더가 이미 있으면 그대로)
  - 사업 시뮬레이션 카드: 숫자가 늘 '—' 이던 것 수정, [📄 사업계획서 보기·내려받기] · [📊 손익표] 버튼
  - 내려받기 파일 이름 '사업이름-사업계획서.md', 알림에 '다운로드' 폴더(Ctrl+J) 안내
  - GH Coin 시간별 보고서가 GH Nano 보고서를 덮어쓰던 경로 · GH Coin '폴더 열기' 가 엉뚱한 폴더를 열던 것
