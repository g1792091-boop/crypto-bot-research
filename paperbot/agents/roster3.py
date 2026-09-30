"""Agent team for paper v3: 34 roles in 11 teams (docs/FINAL-agent-team.md plus the
additions agreed with the owners on 2026-09-30).

Each role: id, Korean name, team, model tier (opus = judgement-heavy, sonnet = repeated
analysis), when it works, what it does, and ``start``: "now" (from the first paper day) or
the condition that brings it in. The dashboard shows this list; the v3 pipelines use it.
Agents never place orders and cannot change the original 195 accounts.
"""

from __future__ import annotations

TEAMS = (
    ("market", "① 시장분석팀"),
    ("plan", "② 매매 계획팀"),
    ("risk", "③ 리스크팀"),
    ("ops", "④ 운영·검증팀"),
    ("dev", "⑤ 개발팀"),
    ("lead", "⑥ 총괄"),
    ("review", "⑦ 손익 복기팀"),
    ("evolve", "⑧ 자기진화팀"),
    ("compare", "⑨ 비교분석팀"),
    ("timing", "⑩ 타점분석팀"),
    ("safety", "⑪ 안전·실거래 준비팀"),
)

# (id, name, team, model, when, duty, start)
ROLES = (
    ("chart_regime", "차트·장세 분석가", "market", "sonnet", "매일 08:00",
     "코인별 추세, 지지·저항, 장세(추세/박스/혼조/고변동), 봉끼리 방향 일치도. 판정은 코드, 해석만", "now"),
    ("derivs_flow", "파생·오더플로 분석가", "market", "sonnet", "매일 08:00",
     "펀딩비, 미결제약정, 롱숏 비율, 청산, 호가 불균형으로 과열·쏠림 경고", "now"),
    ("macro_corr", "매크로·상관 분석가", "market", "sonnet", "매일 08:00",
     "달러·금리·나스닥·변동성 지수와 코인 상관, BTC 대비 상대 강도", "now"),
    ("news_calendar", "뉴스·일정 분석가", "market", "sonnet", "매일 08:00, 월 1회",
     "경제 일정, 해킹·규제, 바이낸스 공지(점검·상장폐지). 월 1회 규제·세금 점검", "now"),
    ("similar_pattern", "유사 패턴·시나리오 분석가", "market", "sonnet", "매일",
     "과거 비슷한 구간 이후 움직임의 분포. 신호는 내지 않음", "1분봉 저장소 완성 후"),
    ("strategist", "전략가", "plan", "opus", "매일 08:00",
     "코인별 허용 방향 초안. 원본 계좌에는 적용하지 않고 '적용했다면'만 기록", "now"),
    ("devils_advocate", "반론 검토관", "plan", "sonnet", "매일 08:00",
     "전략가 계획의 반대 근거 3개 이상", "now"),
    ("risk_officer", "리스크 책임자", "risk", "opus", "08:00, 22:00",
     "계획 승인·축소·거부(확대 불가), 자동 레버리지 감독, 청산 근접·동시 손실 점검, 목표·파산 확률 계산 해석", "now"),
    ("ops_auditor", "운영 감사관", "ops", "sonnet", "매일 22:00, 사고 시",
     "오류·데이터 끊김·장부 불일치 원인, paper와 재계산 일치 결과 해석, 사고 보고서", "now"),
    ("performance", "성과 분석가", "ops", "sonnet", "매일 집계, 주간 판단",
     "표준 지표, 요일·시간대 성과, 백테스트 예상 대비, 봉별·매매법별 순위표 집계", "now"),
    ("validator", "전략 검증관", "ops", "opus", "주간, 이벤트",
     "과최적화 검사, 개선안이 우연인지 판정, 개선판 계좌 승인 전 검증", "now"),
    ("combo_synergy", "조합 시너지 분석가", "ops", "sonnet", "주간",
     "여러 매매법이 동시에 같은 방향일 때 성적(합의 신호), 동시 손실·꼬리 상관", "now"),
    ("league_referee", "리그 심판", "ops", "sonnet", "매일, 주간",
     "계좌 180개를 봉별 동전 봇 3개와 비교해 실력인지 운인지 판정, 합격 기준 확인", "now"),
    ("data_quality", "데이터 품질 감시관", "ops", "sonnet", "매일",
     "빠진 봉, 튀는 가격, 거래소 점검, 마크 가격·펀딩 이상. 이상 데이터로 생긴 거래 표시", "now"),
    ("code_reviewer", "코드 리뷰어", "dev", "opus", "코드 변경 시, 주 1회",
     "버그·보안 리뷰, 바이낸스 API 변경 기록 확인", "now"),
    ("test_writer", "테스트 작성자", "dev", "sonnet", "코드 변경 시",
     "장애 재현 테스트, 미래 정보 사용 검사, 청산 계산 검증", "now"),
    ("team_lead", "팀장", "lead", "sonnet", "08:00, 22:00, 주간",
     "3줄 요약, 사람이 할 일, 용어 풀이. 텔레그램 발송은 코드", "now"),
    ("pnl_reviewer", "손익 복기 분석가", "review", "sonnet", "매일 22:00, 큰 손실 즉시",
     "손실·이익 원인(가짜 돌파, 역추세 등)과 정상 손실 구분. 30건 미만이면 가설로만", "now"),
    ("whatif", "가정 분석가", "review", "sonnet", "매일 22:00",
     "손절·익절·레버리지를 바꿨다면. 계단 익절 효율, 50배 잠금 간격 문제", "now"),
    ("researcher", "전략 연구원", "evolve", "opus", "수시",
     "새 매매법 가설과 명세 카드. 가설 장부에 먼저 확인", "now"),
    ("algo_discovery", "알고리즘 발굴 에이전트", "evolve", "opus", "수시",
     "자동 탐색 작업 설계와 결과 해석", "연구 서버 가동 후"),
    ("self_improve", "자기개선 에이전트", "evolve", "opus", "주간",
     "복기·가정·성과로 수정안 작성. 거래 30건 이상인 매매법만. 승인되면 새 계좌로", "now"),
    ("cio", "CIO 자본배분 에이전트", "evolve", "opus", "주간·월간",
     "실제 돈을 나눌 때 매매법 켜기·끄기와 비중 제안", "실거래 검토 단계"),
    ("approver", "자율 승인관", "evolve", "opus", "수정안이 올 때",
     "수정안·배분안 승인 또는 거부. 만드는 쪽과 분리, 코드 관문 결과는 못 뒤집음", "now"),
    ("learning", "학습 관리 에이전트", "evolve", "sonnet", "주간",
     "배운 점 정리, 가설 장부(지금까지 시험한 것과 결과) 관리, 시도 횟수 집계", "now"),
    ("tf_compare", "봉 비교 분석가", "compare", "sonnet", "주간",
     "같은 매매법의 5분~4시간 계좌 비교. 이웃 봉에서 함께 좋아야 믿을 만함", "now"),
    ("coin_compare", "코인 비교 분석가", "compare", "sonnet", "주간",
     "매매법별 코인 성적, 순서 때문에 놓친 신호의 결과", "now"),
    ("regime_perf", "장세별 성과 분석가", "compare", "sonnet", "주간",
     "추세장·박스장·고변동별 계좌 성적", "now"),
    ("exec_cost", "체결·비용 분석가", "compare", "sonnet", "매일 집계, 주간",
     "신호 계산 지연, 슬리피지, 수수료·펀딩이 손익에서 차지하는 비중, 지정가 그림자 결과", "now"),
    ("entry_timing", "진입 타점 분석가", "timing", "sonnet", "주간",
     "추세 초입·중간·막판, 이동평균 이격, 고점 추격, 큰 캔들 뒤 진입, 진입 직후 역행을 동전 봇과 비교", "now"),
    ("exit_timing", "청산 타점 분석가", "timing", "sonnet", "주간",
     "계단 익절이 챙긴 비율, 너무 이른 잠금, 손절 뒤 원래 방향, 레버리지별 청산", "now"),
    ("rule_keeper", "규칙 지킴이", "safety", "opus", "규칙 변경 시, 주간",
     "고정한 규칙·합격 기준 관리. 바뀌면 새 버전과 새 계좌로만, 결과 보고 기준 옮기기 금지", "now"),
    ("security", "보안 책임자", "safety", "opus", "주 1회",
     "API 키 권한, 서버 접속 기록, 대시보드 로그인 시도, 비밀 정보 노출, 부품 취약점", "now"),
    ("live_readiness", "실거래 준비관", "safety", "opus", "주간",
     "테스트넷 주문 연습, 거래소 규칙 변경 추적, 실거래 전환 체크리스트", "now"),
)

MEETINGS = (
    ("morning", "아침 계획", "매일 08:00 (한국 시간)"),
    ("evening", "저녁 점검", "매일 22:00"),
    ("weekly", "주간 검토", "일요일 21:00"),
    ("incident", "긴급 복기", "큰 손실·청산·데이터 사고 때"),
)


def roster() -> dict:
    return {
        "teams": [{"id": t, "name": n} for t, n in TEAMS],
        "roles": [{"id": r[0], "name": r[1], "team": r[2], "model": r[3], "when": r[4], "duty": r[5],
                   "start": r[6]} for r in ROLES],
        "meetings": [{"id": m[0], "name": m[1], "when": m[2]} for m in MEETINGS],
    }


assert len(ROLES) == 34 and len({r[0] for r in ROLES}) == 34
