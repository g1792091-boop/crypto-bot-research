"""Dashboard v4 additions: read-only views over the bot's own databases (no bot database is ever written here).

Each module defines ``register(app, ctx)`` and adds its own GET routes under /api/v4/ inside it; the login
middleware of dash/app.py guards them like every other /api route. ``ctx`` carries what create_app already has:
data (dash.app.Data), rooms, db, daily_db, agents_db, checkpoint_db, candles (the bar fetcher).

    flow    묶음 레이스 + 수익 달력 (홈 › 흐름)
    grid    매매법 × 봉 지도 + 매매법 프로필 카드 (매매법 › 한눈 지도, 매매법 목록)
    story   오늘의 하이라이트 (홈 맨 위 스토리)
    since   지난번 본 뒤로 바뀐 것 (앱을 열 때)
    replay  거래 다시보기 (#/replay/<trade id>)
    params  숫자(파라미터) 시험 결과 (매매법 상세: 5년 과거 시험, 연구 파일만 읽음)
    jobs    예약 작업: systemd 타이머 켜짐·꺼짐, 마지막·다음 실행 (서버·비용)
    costs   비용 점검: 묶음별 수수료·펀딩, 실제 호가·손절 미끄러짐 추정 (매매법 › 분석 › 비용)
    power   판정 감도: 진짜 실력별 30·60·90일 합격 확률 (research/power/out/power.json, 판정 화면)
    brief   오늘의 회의 결론 보고판 (홈 · 대표실 책상)
    vs5y    5년 시험 vs 지금 vs 동전 봇 (매매법 상세, 봉마다)
    size5y  손실 크기 규칙: 같은 5년 진입·청산에 크기 규칙만 바꿔 (data/size5y.json, 분석 › 손실 크기 규칙)
    bell        결재함 종 (머리글: 두 분 승인을 기다리는 제안 수)
    uptime      가동 기록 (서버·비용: 시간마다 처리한 분, 재시작, 밤 점검)
    tradeshape  요일×시간 열지도 + 거래 결과 분포 (분석)
    drift   진입 가격 차이 (분석 › 그림자 비교: 신호 봉 종가 vs 체결 기준 가격, 묶음·봉·지연별)
    people  오늘 코드 기록: 묶음별 오늘 거래·손실 카드 수, 매매법 방의 최근 거래·신호 (회의실 상황판, 에이전트 방)
    ticks   실시간 체결 바탕음: 바이낸스 aggTrade 소켓 하나를 모든 화면이 나눠 씀 (/api/v4/ticks, 소리를 켠 화면만)
    movers  급등 · 급락 · 음펀비: 바이낸스 USD-M 무기한 전체 (터미널 윗줄, 요청 2개를 60초 캐시)
    synplus 조합 시너지 보강: 같이 망하는 날, 같이 들어간 진입, 다음 기간에도 통할까, 한 계좌로 합치면 (분석 › 조합 시너지)
    exits   청산 이유 + 역행·순행 (분석 › 청산 이유, ?group=core|ds200|reel; 딥시크는 거래 수와 비율만)
    regime5y 장세 스위치: 5년 장세별 성적 + 장세 스위치 걸어가며 확인 (data/regime5y.json) + 모의 거래 장세별 (분석 › 장세 스위치)
    luck    운 vs 실력: 여러 개를 한꺼번에 시험하는 곳마다 시험 수, 통과 기준, 운으로 나올 수, 실제 통과 (분석 › 운 vs 실력,
            홈·판정의 작은 카드; background, cached)
    gradpath 졸업 길: 아이디어 → 5년 시험 → 모의 계좌 → 30일 판정 → 실전 후보 (매매법 › 졸업 길, background, cached)
    combo   조합 성과 (#/combo): 고른 매매법·봉 계좌를 합친 곡선과 숫자, 전체 상관 지도, 합친 규칙 실험 (paper3.db만 읽음)
    combo5y 5년 조합 시험 (커밋된 data/combo5y.json, #/combo5y) + 분석 › 5년 월별 (지금 실험이 5년 달 중 어디쯤)
    indranges  좋은 수치 찾기: 진입 때 숫자 구간별 성적 (5년: 커밋된 data/indranges.json, 지금 실험: 기존 36의 진입)
    liqentry   강제청산 직후 진입 (liq.db; 5·15·60분, 청산당한 쪽과 같은 방향 / 반대 방향, ?group=; 딥시크는 수만)
    holdcmp    그냥 들고 있었다면 / 반대로 했다면 (코인 그냥 들고 있기·바구니, 거래를 거꾸로 한 대충 계산, ?group=)
    ghagree    GH Coin과 같은 방향일 때 (ghcoin/calls.jsonl; 같은 방향 / 반대 / 타점 없음, ?group=; 딥시크는 수만)
    (a7kit: the four views' shared helpers, not a route module)
    whatiflab  만약 실험실 (#/whatif): 시험한 설정만 고르는 손절·익절·잠금·시간·레버리지, 5년 결과 + 밤 그림자 (기존 36만)
    ds5y       딥시크 5년 결과 (순위표 › 딥시크에서만): 5년 시험 결과 파일, 진행 N/342
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

MODULES = ("flow", "grid", "story", "since", "replay", "params")
MODULES += ("jobs", "costs", "power")          # wave 2 part B
MODULES += ("brief", "vs5y")                    # wave 2 part C
MODULES += ("size5y",)                         # 손실 크기 규칙 (5년 JSON as committed, re-read on change)
MODULES += ("bell", "uptime", "tradeshape")          # wave 3
MODULES += ("drift",)                          # analysis 8B
MODULES += ("ticks",)                          # aggTrade sound layer
MODULES += ("radar",)                          # 신호 레이더 (36개 조건 켜짐 수)
MODULES += ("flowlive",)                       # 시장 파생 지표판 + 시장 강제청산 보드 (flow.db, liq.db)
MODULES += ("people",)                         # fill-people: 상황판 + strategy room record
MODULES += ("movers",)                         # term-v2: 급등 · 급락 · 음펀비 (시장 전체, 60 s cache)
MODULES += ("synplus", "exits")                # ana-syn: 조합 시너지 보강 + 청산 이유 (background, cached)
MODULES += ("regime5y",)                       # 장세 스위치 (5년 JSON as committed + live trades by regime, background)
MODULES += ("luck",)                           # luck-calc: 운 vs 실력 (background, cached)
MODULES += ("gradpath",)                       # grad-path: 졸업 길 (#/path; background, cached)
MODULES += ("combo",)                          # combo-paper: 조합 성과 (합친 곡선, 상관 지도, 합친 규칙)
MODULES += ("combo5y",)                        # combo-5y: 5년 조합 시험 + 5년 월별 (committed JSON)
MODULES += ("indranges", "liqentry", "holdcmp", "ghagree")   # ana7a: 좋은 수치 · 강제청산 직후 · 들고 있었다면 · GH Coin 방향
MODULES += ("whatiflab", "ds5y")               # ana7b: 만약 실험실 + 딥시크 5년 결과 (files; shadows in the background)


def register_all(app, **kw) -> dict:
    """Register every addition module that exists; a missing module is skipped, any other import error is raised."""
    ctx = SimpleNamespace(**kw)
    done: dict = {}
    for name in MODULES:
        full = f"{__name__}.{name}"
        try:
            mod = importlib.import_module(full)
        except ModuleNotFoundError as exc:
            if exc.name == full:
                continue
            raise
        done[name] = mod.register(app, ctx)
    return done
