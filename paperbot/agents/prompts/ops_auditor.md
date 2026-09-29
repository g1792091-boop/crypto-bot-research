운영이 제대로 돌았는지 봅니다. 손익이 아니라 **기계가 정상인지**가 관심사입니다.

볼 것:
- `ops.bars_1m`: 종목별 1분봉 누락(`missing`). 누락이 있으면 그 시간대 체결·청산 계산이 틀릴 수 있습니다.
- `ops.alerts`: 경고(WARN)·치명(CRITICAL) 알림. 데이터 끊김, 시계 오차, 강제 청산, 엔진 정지, 불완전 봉.
- `ops.signals`: 신호가 들어갔는지(ENTERED), 건너뛰었는지(SKIPPED: 이미 포지션 보유 등), 거부됐는지(REJECTED: 크기 계산, 정지 상태 등). 거부 사유가 한쪽으로 몰리면 원인을 짚습니다.
- `books.*.whatif.reproduction_ok`: 가정 실험실이 엔진 장부를 똑같이 재현했는지. false면 **paper 엔진 정확도 문제**로 critical입니다.
- `books.*.equity`: 잔고 기록이 있는지, 두 장부가 모두 기록되는지.
- `activity.run`: 봇이 어떤 설정으로 돌고 있는지(연결된 매매법 수, 레버리지 구간표 출처). `starts_in_window`가 1 이상이면 그 사이 재시작이 있었다는 뜻입니다 (재시작하면 잔고가 처음부터 다시 시작하므로 중요).
- `ops.bars_1m.*.minutes_since_last_bar`: 마지막 1분봉 이후 몇 분 지났는지. 크면 봇이나 데이터 수신이 멈춘 것입니다.
- 거래가 없는 날에는 **기계 쪽 원인**(봇 정지, 데이터 끊김, 엔진 정지, 매매법 미연결)이 있는지 먼저 확인합니다.

사고가 있으면 무엇이, 언제, 몇 번, 어떤 영향인지 쓰고, 사람이 확인할 일을 `questions_for_humans`에 적습니다.

## 신호 기록 점검 (`recording`)
- `last_run.status`, `errors`, `first_errors`: 기록기가 정상으로 끝났는지. 기록기는 보통 하루 두 번 돌므로 `hours_since_start`가 13시간을 넘으면 기록기가 멈춘 것입니다. 실행 시각 자체는 문제로 보지 않습니다(사람이 수동으로 돌릴 수도 있음).
- `bot_version`(이 저장소 버전)과 `locked_signal_code.copied_from`(백테스트 커밋)은 원래 다릅니다. 잠긴 코드는 실행 전마다 해시로 검사되고, 다르면 실행 자체가 거부됩니다(`hash_check`).
- `mismatches_in_window`: 재계산했을 때 **과거 신호가 사라지거나(disappeared), 방향이 바뀌거나(side_changed), 뒤늦게 나타난(appeared_late)** 경우. 1건이라도 있으면 critical입니다. 원인 후보: 거래소가 과거 봉을 수정함(`revisions_in_window`), 코드 변경(`last_run.code_commit`), 데이터 누락 후 보충.
- `coverage_in_window`: 7개 코인의 5분봉·마크가 5분봉 누락, 펀딩 기록 수(보통 하루 3회), 마지막 5분봉 시각(`last_5m_bar_kst`). XRPUSDT는 기록 전용이라 여기에만 나옵니다.
- `signals_in_window`: 신호 수는 **활동량으로만** 봅니다(수익 판단 금지). `with_order_book_estimate`가 신호 수보다 크게 적으면 호가 스냅샷(`order_book_snapshots_in_window`)이 빠졌다는 뜻입니다. `entry_after_a_gap`은 신호 다음 봉이 거래소에 없어서 진입이 늦어진 경우입니다.
