"""Mainnet (real money) gates for the executor. OFF unless every gate passes.

The executor talks to Binance USD-M futures through ONE code path (paperbot/testnet.py: orders, stops,
retries). Mainnet differs only in host, keys and the guards below; docs/live-safety.md explains them for
the owners.

Gates (all must hold; any failure refuses the start with a Korean reason):
1. config ``mode`` is "mainnet" (the default and every example is "testnet");
2. the environment flag ``PAPERBOT_LIVE_MAINNET=I_UNDERSTAND`` is set;
3. the keys come from LIVE_API_KEY / LIVE_API_SECRET only, and neither equals the paper runner's
   read-only key (BINANCE_API_KEY / BINANCE_API_SECRET, also read from its env file) nor a testnet key;
4. the host is fapi.binance.com (class-level allowlist, checked again by the executor);
5. the key's permissions (GET /sapi/v1/account/apiRestrictions on api.binance.com) show
   enableWithdrawals = false, enableFutures = true, ipRestrict = true. If api.binance.com cannot be
   reached, nothing can be verified and the start is refused;
6. the risk config is complete (risk.problems() empty) and ``budget_usd`` is set;
7. the futures wallet holds at most budget_usd x 1.2 (a main account by mistake is never traded;
   use a sub-account that holds only the budget).

AI agents never import this module (tests/test_executor.py checks it).
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, Mapping, Optional

from .testnet import TestnetClient, TestnetError

MODE_TESTNET, MODE_MAINNET = "testnet", "mainnet"
MAINNET = "https://fapi.binance.com"
MAINNET_HOSTS = ("fapi.binance.com",)
WALLET_API = "https://api.binance.com"
WALLET_HOSTS = ("api.binance.com",)
FLAG = "PAPERBOT_LIVE_MAINNET"
FLAG_VALUE = "I_UNDERSTAND"
LIVE_KEY_NAMES = ("LIVE_API_KEY", "LIVE_API_SECRET")
TESTNET_KEY_NAMES = ("TESTNET_API_KEY", "TESTNET_API_SECRET")
PAPER_KEY_NAMES = ("BINANCE_API_KEY", "BINANCE_API_SECRET")   # the paper runner's read-only key
PAPER_ENV_FILE = "/etc/paperbot/live.env"
BALANCE_HEADROOM = 1.2


class Refused(Exception):
    """The executor will not start (wrong mode, wrong host, a gate failed, missing settings, ...)."""


class MainnetClient(TestnetClient):
    """The same client, for the real futures exchange. Only fapi.binance.com."""
    __test__ = False
    HOSTS = MAINNET_HOSTS
    DEFAULT_BASE = MAINNET
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-live/0.1"


class KeyCheckClient(TestnetClient):
    """Reads the key's permissions on api.binance.com (one signed GET). Places nothing."""
    __test__ = False
    HOSTS = WALLET_HOSTS
    DEFAULT_BASE = WALLET_API
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-live/0.1"

    def api_restrictions(self) -> dict:
        return self.req("GET", "/sapi/v1/account/apiRestrictions")


# ---------------------------------------------------------------- keys
def read_env_file(path: Optional[str]) -> dict:
    """KEY=VALUE lines of an env file (comments and blanks skipped). {} when missing or unreadable."""
    out: dict = {}
    if not path:
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        return {}
    return out


def _values(env: Mapping, names: Iterable[str]) -> set:
    return {str(env.get(n) or "").strip() for n in names} - {""}


def trading_keys(mode: str, env: Mapping, paper_env: Optional[Mapping] = None) -> tuple[str, str]:
    """The key pair this mode may trade with, or Refused. Testnet: TESTNET_*; mainnet: LIVE_* behind the flag.
    The paper runner's read-only key (env or its env file) is never accepted, nor a key of the other mode."""
    paper = _values(env, PAPER_KEY_NAMES) | _values(paper_env or {}, PAPER_KEY_NAMES)
    if mode == MODE_MAINNET:
        if (env.get(FLAG) or "") != FLAG_VALUE:
            raise Refused(f"실거래 스위치가 꺼져 있습니다: 환경 변수 {FLAG}={FLAG_VALUE} 가 필요합니다")
        names, other = LIVE_KEY_NAMES, _values(env, TESTNET_KEY_NAMES)
        other_text = "테스트넷 키(TESTNET_*)"
    elif mode == MODE_TESTNET:
        names, other = TESTNET_KEY_NAMES, _values(env, LIVE_KEY_NAMES)
        other_text = "실거래 키(LIVE_*)"
    else:
        raise Refused(f"mode={mode!r}: testnet 또는 mainnet만 있습니다")
    key, secret = (str(env.get(n) or "").strip() for n in names)
    if not (key and secret):
        raise Refused(f"{names[0]} / {names[1]} 가 비어 있습니다")
    if key == secret:
        raise Refused(f"{names[0]}와 {names[1]}가 같습니다")
    if {key, secret} & paper:
        raise Refused(f"{names[0]}/{names[1]}가 paper 실행기의 읽기 전용 키(BINANCE_API_KEY)와 같습니다. "
                      "주문용 키를 따로 만드세요")
    if {key, secret} & other:
        raise Refused(f"{names[0]}/{names[1]}가 {other_text}와 같습니다. 모드마다 다른 키를 씁니다")
    return key, secret


# ---------------------------------------------------------------- online checks
def check_permissions(perm: dict) -> list[str]:
    """Korean problems with the key's permissions; empty = acceptable."""
    out = []
    if perm.get("enableWithdrawals") is not False:
        out.append(f"출금 권한이 켜져 있거나 확인되지 않습니다(enableWithdrawals={perm.get('enableWithdrawals')!r}). "
                   "출금이 꺼진 키만 씁니다")
    if perm.get("enableFutures") is not True:
        out.append(f"선물 거래 권한이 없습니다(enableFutures={perm.get('enableFutures')!r})")
    if perm.get("ipRestrict") is not True:
        out.append(f"키에 서버 IP 제한이 없습니다(ipRestrict={perm.get('ipRestrict')!r}). 서버 IP만 허용하세요")
    return out


def permission_warnings(perm: dict) -> list[str]:
    """Permissions the executor does not need (not refused; the owners should turn them off)."""
    names = {"enableInternalTransfer": "계정 간 이체", "permitsUniversalTransfer": "통합 이체",
             "enableMargin": "마진", "enableSpotAndMarginTrading": "현물·마진 거래",
             "enableVanillaOptions": "옵션", "enablePortfolioMarginTrading": "포트폴리오 마진"}
    return [f"{label} 권한({k})이 켜져 있습니다. 실행기에는 필요 없습니다" for k, label in names.items() if perm.get(k)]


def check_balance(wallet: float, budget: float) -> Optional[str]:
    if wallet > budget * BALANCE_HEADROOM + 1e-9:
        return (f"선물 지갑 ${wallet:,.2f}가 정한 금액 ${budget:,.2f}의 {BALANCE_HEADROOM:.1f}배를 넘습니다. "
                "실행기 전용 하위 계정에 정한 금액만 넣으세요(주 계정 사용 방지)")
    return None


def online_gates(perm_reader: Callable[[], dict], wallet: float, budget: float) -> tuple[list[str], list[str]]:
    """(problems, warnings). ``perm_reader`` fetches apiRestrictions; an unreachable or refused check is a problem."""
    problems: list[str] = []
    warnings: list[str] = []
    try:
        perm = perm_reader()
    except (TestnetError, OSError, ValueError) as e:
        problems.append(f"api.binance.com에서 키 권한을 확인하지 못했습니다({e}). 확인 못 하면 시작하지 않습니다")
        perm = None
    if perm is not None:
        if not isinstance(perm, dict):
            problems.append(f"키 권한 응답이 이상합니다: {perm!r}"[:200])
        else:
            problems += check_permissions(perm)
            warnings += permission_warnings(perm)
    bal = check_balance(wallet, budget)
    if bal:
        problems.append(bal)
    return problems, warnings


def env_snapshot(env: Optional[Mapping] = None) -> dict:
    """Only the variables the gates read (never logged)."""
    env = os.environ if env is None else env
    names = (FLAG,) + LIVE_KEY_NAMES + TESTNET_KEY_NAMES + PAPER_KEY_NAMES
    return {n: env.get(n) for n in names if env.get(n) is not None}
