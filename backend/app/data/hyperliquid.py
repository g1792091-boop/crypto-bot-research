"""Hyperliquid — 온체인 무기한 선물 거래소. 모든 계정의 포지션·레버리지가 공개돼 있다.

- 리더보드: 계정별 계좌 규모와 기간(하루 · 일주일 · 한 달 · 전체) 손익·수익률
- 계정 상태(clearinghouseState): 보유 포지션마다 코인 · 수량(+롱/−숏) · 진입가 · 레버리지 · 청산가 · 미실현 손익
"""
from __future__ import annotations

import httpx

from .. import config

INFO = "https://api.hyperliquid.xyz/info"
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"


def leaderboard() -> list[dict]:
    r = httpx.get(LEADERBOARD, timeout=max(30.0, config.HTTP_TIMEOUT * 4))
    r.raise_for_status()
    d = r.json()
    return d.get("leaderboardRows", d) if isinstance(d, dict) else d


def account(address: str) -> dict:
    r = httpx.post(INFO, json={"type": "clearinghouseState", "user": address}, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def to_symbol(coin: str) -> str:
    """Hyperliquid 코인 이름 → 바이낸스 선물 심볼 (kPEPE → 1000PEPEUSDT)."""
    if coin.startswith("k") and coin[1:].isupper():
        return f"1000{coin[1:]}USDT"
    return f"{coin.upper()}USDT"
