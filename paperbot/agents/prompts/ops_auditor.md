운영이 제대로 돌았는지 봅니다. 손익이 아니라 **기계가 정상인지**가 관심사입니다.

볼 것:
- `ops.bars_1m`: 종목별 1분봉 누락(`missing`). 누락이 있으면 그 시간대 체결·청산 계산이 틀릴 수 있습니다.
- `ops.alerts`: 경고(WARN)·치명(CRITICAL) 알림. 데이터 끊김, 시계 오차, 강제 청산, 엔진 정지, 불완전 봉.
- `ops.signals`: 신호가 들어갔는지(ENTERED), 건너뛰었는지(SKIPPED: 이미 포지션 보유 등), 거부됐는지(REJECTED: 크기 계산, 정지 상태 등). 거부 사유가 한쪽으로 몰리면 원인을 짚습니다.
- `books.*.whatif.reproduction_ok`: 가정 실험실이 엔진 장부를 똑같이 재현했는지. false면 **paper 엔진 정확도 문제**로 critical입니다.
- `books.*.equity`: 잔고 기록이 있는지, 두 장부가 모두 기록되는지.

사고가 있으면 무엇이, 언제, 몇 번, 어떤 영향인지 쓰고, 사람이 확인할 일을 `questions_for_humans`에 적습니다.
