"""huntbot settings: paths, the forward start, the warm-up start, the universe and the lineup file.

Everything comes from the environment (the systemd units read /etc/huntbot/huntbot.env) with defaults that work in a
clone of the repository (data under huntbot/data/). No key of any kind is read here or anywhere in huntbot.

    HUNTBOT_DATA           data folder: store.db (bars), events.db (every event, for the AI judge), run.db,
                           snap/ (what the dashboard reads), private/ (DeepSeek money, never served)
    HUNTBOT_UNIVERSE       the 30-coin list file: research/hunt/universe30.json ({"symbols": [...]}) or a coins30
                           universe.json ({"universe": [...]}); default: research/hunt/universe30.json when it exists
    HUNTBOT_LINEUP         the lineup file (default: <data>/lineup.json when it exists, else huntbot/lineup.json)
    HUNTBOT_WARMUP_START   first day of stored history (default 2025-01-01: 638 days before the forward start)
    HUNTBOT_PROCS          worker processes for the runner (default: all CPUs)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FIVE = 300_000
DAY = 86_400_000
FORWARD_START = "2026-10-01"                      # the first day after the studies' data (PREREG_HUNT 15)
FORWARD_START_MS = 1_790_812_800_000              # 2026-10-01 00:00 UTC
WARMUP_START = "2025-01-01"                       # >= 400 days before the forward start (the 365-day label window)
MIN_WARMUP_DAYS = 400
TAG = "[추세 사냥]"
NAME = "추세 사냥"

# PREREG_HUNT 3: the 30 coins, fixed 2026-10-11 08:48 UTC (universe.json sha256 dbe0ed01...). Used only when no
# universe file is found; the status screen then says so.
PREREG_UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT", "LTCUSDT", "MATICUSDT", "BCHUSDT",
                   "LINKUSDT", "AVAXUSDT", "ADAUSDT", "TRBUSDT", "FILUSDT", "FTMUSDT", "ETCUSDT", "DOTUSDT",
                   "NEARUSDT", "EOSUSDT", "CRVUSDT", "SANDUSDT", "ATOMUSDT", "TOMOUSDT", "AXSUSDT", "STORJUSDT",
                   "MKRUSDT", "BLZUSDT", "COMPUSDT", "RUNEUSDT", "WAVESUSDT")
UNIVERSE_REL = os.path.join("research", "hunt", "universe30.json")


def day_ms(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def ms_str(ms: Optional[int]) -> str:
    if ms is None:
        return "-"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def data_dir() -> str:
    return os.path.abspath(os.environ.get("HUNTBOT_DATA") or os.path.join(HERE, "data"))


def path(name: str) -> str:
    return os.path.join(data_dir(), name)


def snap_dir() -> str:
    return os.environ.get("HUNTBOT_SNAP") or path("snap")


def private_dir() -> str:
    return path("private")


def warmup_start_ms() -> int:
    ms = day_ms(os.environ.get("HUNTBOT_WARMUP_START") or WARMUP_START)
    if FORWARD_START_MS - ms < MIN_WARMUP_DAYS * DAY:
        raise ValueError(f"HUNTBOT_WARMUP_START must be at least {MIN_WARMUP_DAYS} days before {FORWARD_START}")
    return ms


def procs() -> int:
    try:
        n = int(os.environ.get("HUNTBOT_PROCS") or 0)
    except ValueError:
        n = 0
    return max(1, n or (os.cpu_count() or 1))


def sha256_file(p: str) -> Optional[str]:
    if not os.path.exists(p):
        return None
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- universe
def universe_file() -> Optional[str]:
    p = os.environ.get("HUNTBOT_UNIVERSE")
    if p:
        return p
    q = os.path.join(ROOT, UNIVERSE_REL)
    return q if os.path.exists(q) else None


def parse_universe(doc: dict) -> list:
    """Both formats: research/hunt/universe30.json {"symbols": [...]} and coins30 universe.json {"universe": [...]}."""
    syms = doc.get("symbols") if isinstance(doc.get("symbols"), list) else doc.get("universe")
    if not isinstance(syms, list) or not syms or not all(isinstance(s, str) and s.endswith("USDT") for s in syms):
        raise ValueError("universe file: want {'symbols': [...]} or {'universe': [...]} of USDT symbols")
    if len(set(syms)) != len(syms):
        raise ValueError("universe file: duplicate symbols")
    return list(syms)


def load_universe(p: Optional[str] = None) -> dict:
    """{"symbols": [...], "source": path or 'PREREG_HUNT 3 (built in)', "sha256": ..., "matches_prereg": bool}."""
    p = p or universe_file()
    if p:
        if not os.path.exists(p):
            raise FileNotFoundError(f"universe file {p} does not exist (HUNTBOT_UNIVERSE)")
        with open(p) as fh:
            syms = parse_universe(json.load(fh))
        return {"symbols": syms, "source": p, "sha256": sha256_file(p),
                "matches_prereg": tuple(syms) == PREREG_UNIVERSE}
    return {"symbols": list(PREREG_UNIVERSE), "source": "PREREG_HUNT 3 (built in: no universe file found)",
            "sha256": None, "matches_prereg": True}


# ---------------------------------------------------------------- lineup
def lineup_file() -> str:
    p = os.environ.get("HUNTBOT_LINEUP")
    if p:
        return p
    q = path("lineup.json")
    return q if os.path.exists(q) else os.path.join(HERE, "lineup.json")
