"""코인 이름 → 바이낸스 USDⓈ-M 무기한 심볼.

문장("에이다 4시간봉 …")이나 검색어("PEPE", "도지")에서 코인을 찾는다.
바이낸스 선물은 단가가 아주 낮은 코인을 1000 단위로 상장한다 (PEPE → 1000PEPEUSDT).
"""
from __future__ import annotations

import re

# 심볼 기본 이름: (한글·영문 별칭들)
COINS: dict[str, tuple[str, ...]] = {
    "BTC": ("비트코인", "비트", "btc", "xbt", "bitcoin"),
    "ETH": ("이더리움", "이더", "eth", "ethereum"),
    "SOL": ("솔라나", "sol", "solana"),
    "XRP": ("리플", "엑스알피", "xrp", "ripple"),
    "BNB": ("바이낸스코인", "비엔비", "bnb"),
    "DOGE": ("도지코인", "도지", "doge", "dogecoin"),
    "ADA": ("에이다", "카르다노", "ada", "cardano"),
    "AVAX": ("아발란체", "아발", "avax", "avalanche"),
    "LINK": ("체인링크", "링크", "link", "chainlink"),
    "SUI": ("수이", "sui"),
    "TRX": ("트론", "trx", "tron"),
    "DOT": ("폴카닷", "dot", "polkadot"),
    "LTC": ("라이트코인", "ltc", "litecoin"),
    "BCH": ("비트코인캐시", "비캐", "bch"),
    "ETC": ("이더리움클래식", "이클", "etc"),
    "TON": ("톤코인", "ton"),
    "NEAR": ("니어프로토콜", "니어", "near"),
    "APT": ("앱토스", "apt", "aptos"),
    "ARB": ("아비트럼", "arb", "arbitrum"),
    "OP": ("옵티미즘", "op", "optimism"),
    "UNI": ("유니스왑", "uni", "uniswap"),
    "ATOM": ("코스모스", "atom", "cosmos"),
    "FIL": ("파일코인", "fil", "filecoin"),
    "INJ": ("인젝티브", "inj", "injective"),
    "WLD": ("월드코인", "wld", "worldcoin"),
    "SEI": ("세이", "sei"),
    "TIA": ("셀레스티아", "tia", "celestia"),
    "HBAR": ("헤데라", "hbar", "hedera"),
    "XLM": ("스텔라루멘", "스텔라", "xlm", "stellar"),
    "ENA": ("에테나", "ena", "ethena"),
    "ONDO": ("온도파이낸스", "온도", "ondo"),
    "AAVE": ("에이브", "aave"),
    "FET": ("페치", "fet"),
    "RENDER": ("렌더", "render"),
    "WIF": ("도그위프햇", "위프", "wif"),
    "ORDI": ("오디", "ordi"),
    "SHIB": ("시바이누", "시바", "shib"),
    "PEPE": ("페페", "pepe"),
    "BONK": ("봉크", "bonk"),
    "FLOKI": ("플로키", "floki"),
}
# 바이낸스 선물에서 1000 단위로 거래되는 코인
THOUSAND = {"SHIB", "PEPE", "BONK", "FLOKI", "SATS", "RATS", "LUNC", "XEC"}


def futures_symbol(base: str) -> str:
    base = base.upper()
    if base.startswith("1000"):
        return base + "USDT"
    return f"{'1000' if base in THOUSAND else ''}{base}USDT"


_ALIASES = sorted(((a, b) for b, al in COINS.items() for a in al), key=lambda x: -len(x[0]))


def find_in_text(text: str) -> str | None:
    """문장에서 코인을 찾아 선물 심볼로. 긴 이름부터 맞춰서 '비트코인캐시'가 '비트코인'으로 잡히지 않게 한다."""
    t = text.lower()
    m = re.search(r"\b((?:1000)?[a-z0-9]{2,12})usdt\b", t)
    if m:
        return m.group(0).upper()
    for alias, base in _ALIASES:
        if re.fullmatch(r"[a-z0-9]+", alias):
            if re.search(rf"(?<![a-z0-9]){alias}(?![a-z0-9])", t):
                return futures_symbol(base)
        elif alias in t:
            return futures_symbol(base)
    return None


def resolve(query: str) -> str:
    """검색창 입력 → 심볼. 모르는 이름이면 영문 티커로 보고 USDT 를 붙인다."""
    q = query.strip()
    hit = find_in_text(q)
    if hit:
        return hit
    base = re.sub(r"[^A-Za-z0-9]", "", q).upper().removesuffix("USDT")
    return futures_symbol(base) if base else "BTCUSDT"
