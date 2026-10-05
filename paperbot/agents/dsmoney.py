"""DeepSeek money in the agents' outputs (written rule D11, docs/paper-v4-rules.md: DeepSeek P&L appears only on the
DeepSeek group screen, a rule tied to the shadow200 blinding).

One switch, ``DS_MONEY_STRICT``. While it is True (the owners' default at the v4 reset) every DeepSeek cell an agent
reads carries counts and ratios only: trades, trades per account, win rate, busts, ROE % (P&L over the starting
balance, a ratio) and the sign against the same-timeframe coin flips. No net P&L, wallet or USDT figure. A DeepSeek
room's alert to the owners that names a money amount is kept as a room note, not sent. Setting it False lets the
debate and the DeepSeek rooms quote dollars again (the owners' call; nothing else changes).

Code only; it reads dicts and returns new dicts, and never touches a database.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

DS_MONEY_STRICT = True

# keys that carry money in the packets the agents read (packets3._stat, debate_packet._cell, rooms.group_accounts_packet,
# digest.tf_stats, cards): dropped from a DeepSeek cell while strict
MONEY_KEYS = frozenset({"pnl", "net_pnl", "net_pnl_24h", "wallet", "median_wallet", "gross_before_costs", "costs",
                        "cost_per_trade", "move_before_costs", "fees", "funding", "equity_after", "margin",
                        "pnl_before_costs", "gross_pnl"})

# a money amount in model-written text: USDT / $ / 달러 next to digits (full-width forms folded first)
_MONEY = re.compile(r"(?i)\$\s*[+-]?\d|\d\s*\$|\d\s*(?:usdt|usd|달러)|(?:usdt|달러)\s*[+-]?\d")

STRICT_NOTE_KO = "딥시크는 돈 숫자를 말하지 않음 (개수·비율만: 거래 수, 승률, 파산, ROE %, 같은 봉 동전 대비 부호)"


def has_money(text: Any) -> bool:
    """True when ``text`` names a money amount (USDT, $ or 달러 with digits)."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_MONEY.search(unicodedata.normalize("NFKC", text)))


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def roe_pct(pnl: Any, accounts: Any, initial: float) -> Optional[float]:
    """P&L over the accounts' starting balance, in % (a ratio, not money); None when unknown."""
    p, n = _num(pnl), _num(accounts)
    if p is None or not n or not initial:
        return None
    return round(100.0 * p / (n * initial), 2)


def sign_vs(mine: Optional[dict], flips: Optional[dict]) -> Optional[str]:
    """'above' / 'below' / 'equal': a group cell's P&L per account against the same-timeframe coin flips' (the sign
    only, no amount); None when either side is missing or has no trades."""
    if not isinstance(mine, dict) or not isinstance(flips, dict):
        return None
    a, b = _num(mine.get("net_pnl")), _num(flips.get("net_pnl"))
    na, nb = _num(mine.get("accounts")), _num(flips.get("accounts"))
    if a is None or b is None or not na or not nb or not mine.get("trades") or not flips.get("trades"):
        return None
    x, y = a / na, b / nb
    return "above" if x > y else "below" if x < y else "equal"


def scrub(obj: Any) -> Any:
    """``obj`` with every MONEY_KEYS key removed at any depth (lists and dicts; other values as they are)."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in MONEY_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def strict_cell(cell: Optional[dict], flips: Optional[dict] = None) -> Optional[dict]:
    """A DeepSeek debate cell (debate_packet._cell, made from packets3 numbers) as counts and ratios only: accounts,
    trades, trades_per_account, win_rate, busts, small_sample and ``vs_coin_flip`` (the sign of P&L per account
    against the same-timeframe coin flips; ``flips`` is that coin-flip cell, or None)."""
    if not isinstance(cell, dict):
        return cell
    out = {k: cell[k] for k in ("accounts", "trades", "trades_per_account", "win_rate", "busts", "small_sample")
           if k in cell}
    if flips is not None:
        out["vs_coin_flip"] = sign_vs(cell, flips)
    return out
