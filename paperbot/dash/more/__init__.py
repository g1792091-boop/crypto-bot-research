"""Dashboard v4 additions: read-only views over the bot's own databases (no bot database is ever written here).

Each module defines ``register(app, ctx)`` and adds its own GET routes under /api/v4/ inside it; the login
middleware of dash/app.py guards them like every other /api route. ``ctx`` carries what create_app already has:
data (dash.app.Data), rooms, db, daily_db, agents_db, checkpoint_db, candles (the bar fetcher).

    flow    묶음 레이스 + 수익 달력 (홈 › 흐름)
    grid    매매법 × 봉 지도 + 매매법 프로필 카드 (매매법 › 한눈 지도, 매매법 목록)
    story   오늘의 하이라이트 (홈 맨 위 스토리)
    since   지난번 본 뒤로 바뀐 것 (앱을 열 때)
    replay  거래 다시보기 (#/replay/<trade id>)
    bell        결재함 종 (머리글: 두 분 승인을 기다리는 제안 수)
    uptime      가동 기록 (서버·비용: 시간마다 처리한 분, 재시작, 밤 점검)
    tradeshape  요일×시간 열지도 + 거래 결과 분포 (분석)
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

MODULES = ("flow", "grid", "story", "since", "replay")
MODULES += ("bell", "uptime", "tradeshape")          # wave 3


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
