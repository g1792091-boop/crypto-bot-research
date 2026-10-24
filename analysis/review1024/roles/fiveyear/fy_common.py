"""Shared definitions of the five-year role study (analysis/review1024/roles/fiveyear).

The friend's principle on 5 years: an ENTRY strategy (range / pullback / breakout / reversal / timing; trend-role
strategies kept as a control) on its own timeframe, filtered by a TREND SOURCE read on the last CLOSED higher bar
(15m -> 1h/4h/1d, 30m -> 1h/4h/1d, 1h -> 4h/1d, 4h -> 1d). Condition of a signal: with (source side == signal side),
against (opposite), neutral (source 0). Outcomes come from the data layer's dense grid (rolesdata.add_outcomes): w35 =
the owners' live exits (35x, net-ROE -50 % stop, ladder 12 -> 10 then every 5 %), w30, w35s20 (-20 % stop), a2 (2 x ATR14
of the signal bar + ladder, 30x). Costs: 0.124 % round trip (WOO X Pro taker 0.042 % + slippage 0.02 % each side);
TetherMax payback NOT included (common.PAYBACK adds 0.0756 % price = +2.65 ROE points at 35x).

Periods are fixed before any result was read: SELECT 2021-01-01 .. 2024-01-01, CONFIRM 2024-01-01 .. 2026-10-01
(read once), LATE 2026-01-01 .. 2026-10-23 00:00 UTC, FWD 2026-10-05 15:00 .. 10-24 15:00 UTC (the 19 forward days).
"""
import os
import sys

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
from common import *            # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
SHM = "/dev/shm/claude_fiveyear"   # RAM-backed scratch for the big accumulators (disk is nearly full); deleted at the end
os.makedirs(SHM, exist_ok=True)

EDGES = np.array([ms("2021-01-01"), ms("2022-01-01"), ms("2023-01-01"), ms("2024-01-01"), ms("2025-01-01"),
                  ms("2026-01-01"), ms("2026-10-01"), RD.PERIODS["fwd"][0], GRID_END, RD.PERIODS["fwd"][1]], np.int64)
BLOCKS = ["Y21", "Y22", "Y23", "Y24", "Y25", "Y26a", "O26a", "F1", "F2"]
NB = len(BLOCKS)
PER = {"SEL": [0, 1, 2], "CONF": [3, 4, 5], "LATE": [5, 6, 7], "FWD": [7, 8]}
PER_KO = {"SEL": "고르기 2021-01~2023-12", "CONF": "확인 2024-01~2026-09", "LATE": "2026-01~10-22",
          "FWD": "마지막 19일 10-06~10-24 KST"}
PAIRS = [("15m", "1h"), ("15m", "4h"), ("15m", "1d"), ("30m", "1h"), ("30m", "4h"), ("30m", "1d"),
         ("1h", "4h"), ("1h", "1d"), ("4h", "1d")]
FRIEND_PAIRS = {("15m", "1h"), ("30m", "1h"), ("1h", "4h"), ("4h", "1d")}     # the trend bot's 'auto' mapping

# statistic columns accumulated per signal row (K)
STATS = ["n", "nlong", "w35", "w35_2", "w35o", "w35o_2", "w35x", "win", "w30", "w30o", "s20", "s20o", "a2", "a2o", "a2_2"]
K = len(STATS)
SI = {s: i for i, s in enumerate(STATS)}

JSRC = ["RAW3", "DIR", "DIR_ADX20", "V2OF4", "V4OF4", "TB22", "TB21"]


def sources():
    R = RD.roles()
    tr = list(R["roles"]["trend_incl_dual"])
    return [("c", s) for s in tr] + [("l", s) for s in tr] + [("j", s) for s in JSRC]


def src_label(kind, s):
    return f"{kind}:{s}"


def row_stats(side, out):
    """K statistic columns per row from add_outcomes columns (the row's side and its opposite twin)."""
    n = len(side)
    M = np.zeros((n, K))
    w = out["w35_roe"]
    o = out["w35_opp_roe"]
    M[:, 0] = 1.0
    M[:, 1] = side > 0
    M[:, 2] = w
    M[:, 3] = w * w
    M[:, 4] = o
    M[:, 5] = o * o
    M[:, 6] = w * o
    M[:, 7] = w > 0
    M[:, 8] = out["w30_roe"]
    M[:, 9] = out["w30_opp_roe"]
    M[:, 10] = out["w35s20_roe"]
    M[:, 11] = out["w35s20_opp_roe"]
    M[:, 12] = out["a2_roe"]
    M[:, 13] = out["a2_opp_roe"]
    M[:, 14] = out["a2_roe"] ** 2
    return M


NMON = 70                         # months 2021-01 .. 2026-10 (month clusters for the errors)


def month_of(t):
    d = pd.to_datetime(np.asarray(t, np.int64), unit="ms", utc=True)
    m = np.array((d.year - 2021) * 12 + d.month - 1, dtype=np.int64)
    m[(m < 0) | (m >= NMON)] = -1
    return m


def block_of(t):
    b = np.searchsorted(EDGES, np.asarray(t, np.int64), side="right") - 1
    b[(b < 0) | (b >= NB)] = -1
    return b
