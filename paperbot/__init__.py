"""Paper trading engine for the crypto futures bot (no real orders)."""

from .config import Settings, Tier
from .engine import PaperEngine
from .margin import BracketTier, Brackets, liquidation_price
from .models import LONG, SHORT, Bar, Signal
from .sizing import size_position, tp_from_roe

__all__ = [
    "Settings", "Tier", "PaperEngine", "BracketTier", "Brackets",
    "liquidation_price", "LONG", "SHORT", "Bar", "Signal", "size_position",
    "tp_from_roe",
]
