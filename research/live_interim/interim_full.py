"""The whole rule bot paper v4 run so far, every account and every angle (read-only; for the owners to paste).

    python3 research/live_interim/interim_full.py [--db /var/lib/paperbot/paper3.db]
                                                 [--daily /var/lib/paperbot/daily3.db] [--ds-money]

The long companion of interim.py. Opens paper3.db (and daily3.db when present) read-only and prints, in Korean:
the run, each group and timeframe with hold time and long share, the cost split per trade (price move before costs,
fees, funding), the live result against the 5-year backtest of the same cells (the full grid's default numbers with
the live exit, test period 2024-01 .. 2026-09: per timeframe, per cell rank correlation, backtest-better half vs
worse half, the watch list against the rest), all 36 core strategies x 4 timeframes, all 44 DeepSeek definitions
(labels only), the reel and the coin flips, coin x side, long vs short per day next to each coin's move, exit reasons
with how far stopped trades had gone in favour first, leverage and tier, KST hours and weekdays, what happened to
every signal (entered, skipped, rejected), drawdowns and open positions, measured order-book costs, and the
server's nightly checks (replay parity, stop slippage, data quality). DeepSeek money figures are hidden unless
--ds-money (owners' D11): counts, win rates and up / down labels only. Standard library only; nothing is written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict

START = 5000.0
GROUP_OF_KIND = {"strategy": "core", "random": "flip", "ds200": "ds200", "reel": "reel", "copy": "extra",
                 "newlab": "extra"}           # paperbot/accounts.py GROUP_OF_KIND
GROUP_KO = {"core": "규칙봇 36개", "ds200": "딥시크", "reel": "5분 단타", "flip": "동전 던지기", "extra": "추가 계좌"}
TF_ORDER = ("5m", "15m", "30m", "1h", "4h", "1d")
CORE_TFS = ("15m", "30m", "1h", "4h")
WATCH_CORE = ("DOGE", "N19_FIB_CHOP", "S4_BB_BBP", "N03_ADX_GC", "N09_ALLIG_AROON", "N13_3OUTSIDE", "OBV_S",
              "N10_HA_PSAR")
WATCH_DS = ("F10_OTE", "F7_RF_TRIPLE", "F9_FVG", "F7_RF_ONLY", "F12_MSS_DISP", "F5_BOX", "F1_PVT_DIV", "F11_TSOUP")
KST = dt.timezone(dt.timedelta(hours=9))
WEEKDAY_KO = "월화수목금토일"
# Full grid (research/fullgrid, diag/strat_report.json), default numbers with the live exit, test period
# 2024-01 .. 2026-09, per signal: (signals, win rate, mean P&L per trade as a share of the wallet, payoff).
BT = {
    "DOGE@15m": (8680, 0.629, -0.00957, 0.418),
    "DOGE@30m": (5224, 0.687, -0.00794, 0.337),
    "DOGE@1h": (2411, 0.732, -0.00492, 0.297),
    "DOGE@4h": (0, None, None, None),
    "N01_ST_EMA@15m": (16701, 0.600, -0.01132, 0.445),
    "N01_ST_EMA@30m": (7660, 0.660, -0.00945, 0.366),
    "N01_ST_EMA@1h": (3435, 0.707, -0.00644, 0.322),
    "N01_ST_EMA@4h": (234, 0.782, -0.00123, 0.262),
    "N02_ST_KST@15m": (14762, 0.608, -0.01115, 0.435),
    "N02_ST_KST@30m": (6886, 0.661, -0.00991, 0.359),
    "N02_ST_KST@1h": (3053, 0.708, -0.00672, 0.316),
    "N02_ST_KST@4h": (204, 0.779, -0.00225, 0.255),
    "N03_ADX_GC@15m": (613, 0.623, -0.00945, 0.432),
    "N03_ADX_GC@30m": (247, 0.692, -0.00918, 0.311),
    "N03_ADX_GC@1h": (141, 0.709, -0.00746, 0.306),
    "N03_ADX_GC@4h": (7, 0.857, 0.00628, 0.238),
    "N04_ST_KLINGER@15m": (49333, 0.609, -0.01109, 0.435),
    "N04_ST_KLINGER@30m": (23324, 0.663, -0.01004, 0.352),
    "N04_ST_KLINGER@1h": (10291, 0.715, -0.00659, 0.305),
    "N04_ST_KLINGER@4h": (699, 0.740, -0.00738, 0.252),
    "N05_PSAR_POC@15m": (4085, 0.592, -0.01273, 0.440),
    "N05_PSAR_POC@30m": (1944, 0.647, -0.01175, 0.359),
    "N05_PSAR_POC@1h": (894, 0.747, -0.00223, 0.308),
    "N05_PSAR_POC@4h": (50, 0.740, -0.00898, 0.234),
    "N06_MACD_ORB@15m": (3903, 0.592, -0.01223, 0.448),
    "N06_MACD_ORB@30m": (2551, 0.640, -0.01178, 0.370),
    "N06_MACD_ORB@1h": (1603, 0.697, -0.00810, 0.316),
    "N06_MACD_ORB@4h": (132, 0.727, -0.00684, 0.282),
    "N07_ICHI_CMO@15m": (6652, 0.597, -0.01153, 0.448),
    "N07_ICHI_CMO@30m": (3156, 0.671, -0.00780, 0.368),
    "N07_ICHI_CMO@1h": (1371, 0.683, -0.00965, 0.319),
    "N07_ICHI_CMO@4h": (101, 0.802, 0.00235, 0.278),
    "N08_ICHI_WR@15m": (1077, 0.573, -0.01414, 0.457),
    "N08_ICHI_WR@30m": (490, 0.637, -0.01150, 0.383),
    "N08_ICHI_WR@1h": (228, 0.728, -0.00564, 0.296),
    "N08_ICHI_WR@4h": (10, 1.000, 0.02387, None),
    "N09_ALLIG_AROON@15m": (7930, 0.610, -0.01125, 0.430),
    "N09_ALLIG_AROON@30m": (3846, 0.674, -0.00905, 0.345),
    "N09_ALLIG_AROON@1h": (1628, 0.725, -0.00434, 0.318),
    "N09_ALLIG_AROON@4h": (97, 0.825, 0.00247, 0.242),
    "N10_HA_PSAR@15m": (24941, 0.609, -0.01207, 0.425),
    "N10_HA_PSAR@30m": (11003, 0.670, -0.00897, 0.354),
    "N10_HA_PSAR@1h": (4719, 0.703, -0.00810, 0.305),
    "N10_HA_PSAR@4h": (230, 0.757, -0.00596, 0.244),
    "N11_BREAKAWAY@15m": (363, 0.606, -0.01155, 0.429),
    "N11_BREAKAWAY@30m": (161, 0.634, -0.01597, 0.327),
    "N11_BREAKAWAY@1h": (69, 0.768, 0.00179, 0.326),
    "N11_BREAKAWAY@4h": (6, 0.833, -0.00351, 0.160),
    "N12_ICHI_AO@15m": (7723, 0.608, -0.01077, 0.439),
    "N12_ICHI_AO@30m": (3683, 0.665, -0.00877, 0.365),
    "N12_ICHI_AO@1h": (1643, 0.721, -0.00553, 0.309),
    "N12_ICHI_AO@4h": (110, 0.745, -0.00712, 0.247),
    "N13_3OUTSIDE@15m": (6358, 0.594, -0.01344, 0.425),
    "N13_3OUTSIDE@30m": (2877, 0.657, -0.01050, 0.355),
    "N13_3OUTSIDE@1h": (1096, 0.711, -0.00598, 0.321),
    "N13_3OUTSIDE@4h": (52, 0.808, 0.00126, 0.254),
    "N14_ICHI_RSI@15m": (1, 1.000, 0.03183, None),
    "N14_ICHI_RSI@30m": (0, None, None, None),
    "N14_ICHI_RSI@1h": (0, None, None, None),
    "N14_ICHI_RSI@4h": (0, None, None, None),
    "N15_KC_AO@15m": (33, 0.485, -0.03573, 0.345),
    "N15_KC_AO@30m": (27, 0.815, 0.00985, 0.343),
    "N15_KC_AO@1h": (10, 0.800, 0.00447, 0.316),
    "N15_KC_AO@4h": (0, None, None, None),
    "N16_BBRSI@15m": (6318, 0.617, -0.01089, 0.420),
    "N16_BBRSI@30m": (3038, 0.668, -0.00974, 0.348),
    "N16_BBRSI@1h": (1353, 0.693, -0.01052, 0.292),
    "N16_BBRSI@4h": (74, 0.784, -0.00087, 0.264),
    "N17_KC_RSI@15m": (68869, 0.634, -0.01211, 0.375),
    "N17_KC_RSI@30m": (35400, 0.677, -0.01019, 0.324),
    "N17_KC_RSI@1h": (15818, 0.697, -0.00984, 0.291),
    "N17_KC_RSI@4h": (889, 0.713, -0.01098, 0.247),
    "N18_VWMA_MACD@15m": (54003, 0.609, -0.01135, 0.433),
    "N18_VWMA_MACD@30m": (24828, 0.670, -0.00879, 0.358),
    "N18_VWMA_MACD@1h": (10355, 0.692, -0.00939, 0.308),
    "N18_VWMA_MACD@4h": (738, 0.748, -0.00629, 0.255),
    "N19_FIB_CHOP@15m": (4486, 0.632, -0.00868, 0.421),
    "N19_FIB_CHOP@30m": (1937, 0.681, -0.00820, 0.342),
    "N19_FIB_CHOP@1h": (799, 0.735, -0.00415, 0.304),
    "N19_FIB_CHOP@4h": (44, 0.727, -0.00973, 0.240),
    "N20_EMA9_CHOP@15m": (24543, 0.592, -0.01209, 0.452),
    "N20_EMA9_CHOP@30m": (11155, 0.645, -0.01142, 0.366),
    "N20_EMA9_CHOP@1h": (4762, 0.710, -0.00666, 0.314),
    "N20_EMA9_CHOP@4h": (340, 0.685, -0.01287, 0.263),
    "N21_ST_RSI_ADX@15m": (0, None, None, None),
    "N21_ST_RSI_ADX@30m": (0, None, None, None),
    "N21_ST_RSI_ADX@1h": (0, None, None, None),
    "N21_ST_RSI_ADX@4h": (0, None, None, None),
    "N22_VORTEX_PSAR@15m": (41247, 0.598, -0.01235, 0.435),
    "N22_VORTEX_PSAR@30m": (19377, 0.662, -0.00961, 0.359),
    "N22_VORTEX_PSAR@1h": (8372, 0.703, -0.00727, 0.316),
    "N22_VORTEX_PSAR@4h": (534, 0.787, -0.00183, 0.248),
    "N23_HA_ST@15m": (64707, 0.607, -0.01098, 0.436),
    "N23_HA_ST@30m": (30119, 0.663, -0.00976, 0.355),
    "N23_HA_ST@1h": (12814, 0.712, -0.00647, 0.311),
    "N23_HA_ST@4h": (810, 0.810, 0.00262, 0.268),
    "N24_DMI@15m": (23493, 0.601, -0.01225, 0.434),
    "N24_DMI@30m": (10953, 0.663, -0.00983, 0.356),
    "N24_DMI@1h": (4742, 0.723, -0.00540, 0.307),
    "N24_DMI@4h": (341, 0.742, -0.00618, 0.262),
    "N25_DST_CCI@15m": (24385, 0.601, -0.01256, 0.433),
    "N25_DST_CCI@30m": (11901, 0.650, -0.01177, 0.354),
    "N25_DST_CCI@1h": (5179, 0.712, -0.00643, 0.313),
    "N25_DST_CCI@4h": (323, 0.793, -0.00036, 0.257),
    "OBV_B@15m": (20003, 0.596, -0.01247, 0.434),
    "OBV_B@30m": (9774, 0.653, -0.01086, 0.357),
    "OBV_B@1h": (4380, 0.697, -0.00851, 0.309),
    "OBV_B@4h": (262, 0.702, -0.01128, 0.262),
    "OBV_S@15m": (6367, 0.594, -0.01161, 0.450),
    "OBV_S@30m": (3054, 0.647, -0.01143, 0.361),
    "OBV_S@1h": (1437, 0.713, -0.00668, 0.309),
    "OBV_S@4h": (100, 0.700, -0.01237, 0.255),
    "S1_EMA_RSI_CHOP@15m": (94, 0.660, -0.00552, 0.418),
    "S1_EMA_RSI_CHOP@30m": (43, 0.465, -0.04288, 0.290),
    "S1_EMA_RSI_CHOP@1h": (22, 0.818, 0.00428, 0.270),
    "S1_EMA_RSI_CHOP@4h": (1, 1.000, 0.01818, None),
    "S2_ST_ROC@15m": (49164, 0.600, -0.01099, 0.446),
    "S2_ST_ROC@30m": (23649, 0.658, -0.00973, 0.363),
    "S2_ST_ROC@1h": (10090, 0.709, -0.00646, 0.318),
    "S2_ST_ROC@4h": (742, 0.737, -0.00664, 0.265),
    "S3_CMO_SANDWICH@15m": (4329, 0.585, -0.01318, 0.444),
    "S3_CMO_SANDWICH@30m": (1895, 0.634, -0.01349, 0.355),
    "S3_CMO_SANDWICH@1h": (831, 0.700, -0.00702, 0.324),
    "S3_CMO_SANDWICH@4h": (49, 0.673, -0.01667, 0.242),
    "S4_BB_BBP@15m": (18163, 0.584, -0.01305, 0.451),
    "S4_BB_BBP@30m": (8792, 0.653, -0.01057, 0.364),
    "S4_BB_BBP@1h": (3877, 0.701, -0.00752, 0.317),
    "S4_BB_BBP@4h": (327, 0.743, -0.00670, 0.256),
    "S5_DONCHIAN_MFI@15m": (937, 0.629, -0.00948, 0.422),
    "S5_DONCHIAN_MFI@30m": (476, 0.655, -0.01115, 0.348),
    "S5_DONCHIAN_MFI@1h": (197, 0.706, -0.00956, 0.284),
    "S5_DONCHIAN_MFI@4h": (13, 0.769, -0.00751, 0.201),
    "S6_EMA_DMI_ADX@15m": (4777, 0.624, -0.01100, 0.411),
    "S6_EMA_DMI_ADX@30m": (2503, 0.682, -0.00840, 0.342),
    "S6_EMA_DMI_ADX@1h": (1000, 0.723, -0.00612, 0.297),
    "S6_EMA_DMI_ADX@4h": (73, 0.808, -0.00272, 0.208),
    "V39_ALL@15m": (18438, 0.618, -0.01095, 0.424),
    "V39_ALL@30m": (8753, 0.678, -0.00794, 0.355),
    "V39_ALL@1h": (3716, 0.708, -0.00727, 0.308),
    "V39_ALL@4h": (249, 0.771, -0.00344, 0.253),
    "V45_AMB@15m": (6495, 0.583, -0.01470, 0.427),
    "V45_AMB@30m": (3376, 0.644, -0.01288, 0.346),
    "V45_AMB@1h": (1443, 0.707, -0.00812, 0.298),
    "V45_AMB@4h": (64, 0.766, -0.00368, 0.258),
}


def pct(x, nd=2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def wr(x) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def tf_key(tf: str) -> int:
    return TF_ORDER.index(tf) if tf in TF_ORDER else 9


def mean(xs):
    xs = list(xs)
    return st.mean(xs) if xs else None


def median(xs):
    xs = list(xs)
    return st.median(xs) if xs else None


def q90(xs):
    xs = sorted(xs)
    return xs[int(0.9 * (len(xs) - 1))] if xs else None


def stats(rows: list) -> dict:
    r = [t["ret"] for t in rows]
    return {"n": len(r), "win": sum(x > 0 for x in r) / len(r) if r else None, "mean": mean(r)}


def ranks(xs: list) -> list:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list, b: list):
    if len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def range95(xs: list):
    """(low, high) of a 95% range for the mean of xs (normal approximation), None below 3 values."""
    if len(xs) < 3:
        return None
    m, s = st.mean(xs), st.stdev(xs)
    t = {3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26}.get(len(xs), 1.96)
    h = t * s / math.sqrt(len(xs))
    return m - h, m + h


def load(db: str):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    accts = {r["account_id"]: dict(r) for r in conn.execute(
        "SELECT account_id, strategy, timeframe, kind, created_ts FROM accounts")}
    trades = []
    for r in conn.execute("SELECT account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                          "equity_after, data FROM trades ORDER BY exit_time, id"):
        t = dict(r)
        try:
            d = json.loads(t.pop("data") or "{}")
        except ValueError:
            d = {}
        before = t["equity_after"] - t["pnl"]
        t["before"] = before
        t["ret"] = t["pnl"] / before if before > 0 else 0.0
        fees, fund = float(d.get("fees") or 0.0), float(d.get("funding") or 0.0)
        t["fee_ret"] = fees / before if before > 0 else 0.0
        t["fund_ret"] = fund / before if before > 0 else 0.0
        t["gross_ret"] = t["ret"] + t["fee_ret"] + t["fund_ret"]
        t["side"] = int(d.get("side") or 0)
        t["tier"] = d.get("tier") or "?"
        t["hold_h"] = (t["exit_time"] - t["entry_time"]) / 3_600_000
        ep, sp = d.get("entry_price"), d.get("stop_initial") or d.get("stop_price")
        mfe = d.get("mfe_price")
        t["mfe_r"] = None
        if ep and sp and mfe and t["side"] and abs(ep - sp) > 0:
            t["mfe_r"] = t["side"] * (mfe / ep - 1) / (abs(ep - sp) / ep)
        trades.append(t)
    state = None
    try:
        row = conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        state = json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError):
        state = None
    try:
        fills = [dict(r) for r in conn.execute(
            "SELECT ts, account_id, symbol, event, status, notional, slip_best FROM fill_costs")]
    except sqlite3.Error:
        fills = []
    try:
        outcomes = [dict(r) for r in conn.execute(
            "SELECT account_id, status, reason, COUNT(*) AS n FROM outcomes GROUP BY account_id, status, reason")]
    except sqlite3.Error:
        outcomes = []
    try:
        moves = {}
        for r in conn.execute("SELECT symbol, ts, open, close FROM live_bars ORDER BY ts"):
            d0 = day(r["ts"])
            m = moves.setdefault((d0, r["symbol"]), [r["open"], r["close"]])
            m[1] = r["close"]
    except sqlite3.Error:
        moves = {}
    try:
        runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    except sqlite3.Error:
        runs = None
    conn.close()
    return accts, trades, state, fills, outcomes, moves, runs


def load_daily(path: str):
    if not path or not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out = {}
    for name, q in (("reports", "SELECT day, data FROM reports ORDER BY day"),
                    ("mismatches", "SELECT day, account_id, data FROM mismatches ORDER BY day"),
                    ("stop_slips", "SELECT day, account_id, exit_reason, status, paper_bps, real_bps, diff_usd "
                                   "FROM stop_slips")):
        try:
            out[name] = [dict(r) for r in conn.execute(q)]
        except sqlite3.Error:
            out[name] = []
    conn.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/var/lib/paperbot/paper3.db")
    ap.add_argument("--daily", default="/var/lib/paperbot/daily3.db")
    ap.add_argument("--ds-money", action="store_true")
    a = ap.parse_args(argv)
    accts, trades, state, fills, outcomes, moves, runs = load(a.db)
    engines = (state or {}).get("engines", {})
    by_acct = defaultdict(list)
    for t in trades:
        by_acct[t["account_id"]].append(t)
    for aid, ac in accts.items():
        ac["group"] = GROUP_OF_KIND.get(ac["kind"], "other")
        ts = by_acct.get(aid, [])
        ac["equity"] = ts[-1]["equity_after"] if ts else START
        ac["n"] = len(ts)
        e = engines.get(aid) or {}
        ac["max_dd"] = e.get("max_drawdown")
        ac["bust"] = bool(e.get("bust")) or ac["equity"] < 10
        ac["open"] = e.get("position")
        ac["mark"] = (e.get("last_mark") or {})
    for t in trades:
        t["group"] = accts.get(t["account_id"], {}).get("group", "other")
        t["tf"] = accts.get(t["account_id"], {}).get("timeframe", "?")
        t["strategy"] = accts.get(t["account_id"], {}).get("strategy", "?")
    originals = [ac for ac in accts.values() if ac["group"] != "extra"]
    d0 = min(ac["created_ts"] for ac in originals) if originals else 0
    last = max((t["exit_time"] for t in trades), default=d0)
    days = max(0.0, (last - d0) / 86_400_000)
    hide = lambda g: g == "ds200" and not a.ds_money  # noqa: E731
    core = [t for t in trades if t["group"] == "core"]
    out: list[str] = []
    P = out.append

    # ------------------------------------------------------------------ 0. run
    P("[규칙봇 paper v4 전체 성적]")
    cnt = Counter(ac["group"] for ac in accts.values())
    tcnt = Counter(t["group"] for t in trades)
    P(f"시작 {day(d0)} · 마지막 거래 {day(last)} · {days:.1f}일 · 계좌 {len(accts)}개 · 거래 {len(trades)}건"
      + (f" · 봇 시작 기록 {runs}번" if runs is not None else ""))
    P("묶음별 계좌(거래): " + " · ".join(f"{GROUP_KO.get(g, g)} {cnt[g]}({tcnt[g]}건)"
                                          for g in GROUP_KO if cnt[g]))

    # ------------------------------------------------------------------ 1. group x tf
    P("")
    P("[1. 묶음 × 봉] 계좌(거래 있는) | 거래 | 승률 | 거래당 | 평균 이익 / 평균 손실 | 롱 비율 | 평균 보유 | "
      "늘어남/줄어듦/파산 | 잔고 중앙값 | 최대 낙폭 중앙값")
    groups = defaultdict(list)
    for ac in accts.values():
        groups[(ac["group"], ac["timeframe"])].append(ac)
    gkeys = sorted(groups, key=lambda k: (list(GROUP_KO).index(k[0]) if k[0] in GROUP_KO else 9, tf_key(k[1])))
    for g, tf in gkeys:
        acs = groups[(g, tf)]
        rows = [t for ac in acs for t in by_acct.get(ac["account_id"], [])]
        s = stats(rows)
        traded = sum(ac["n"] > 0 for ac in acs)
        up = sum(ac["equity"] > START for ac in acs)
        bust = sum(ac["bust"] for ac in acs)
        down = len(acs) - up - bust - sum(ac["equity"] == START and not ac["bust"] for ac in acs)
        longs = sum(t["side"] > 0 for t in rows)
        hold = mean(t["hold_h"] for t in rows)
        dds = [ac["max_dd"] for ac in acs if ac["max_dd"] is not None]
        if hide(g):
            mn = "가림" if s["mean"] is None else ("플러스" if s["mean"] > 0 else "마이너스")
            wl = med = dd = "가림"
        else:
            mn = pct(s["mean"])
            wl = f"{pct(mean(t['ret'] for t in rows if t['ret'] > 0), 1)} / " \
                 f"{pct(mean(t['ret'] for t in rows if t['ret'] <= 0), 1)}"
            med = f"${st.median(ac['equity'] for ac in acs):,.0f}"
            dd = f"{median(dds) * 100:.0f}%" if dds else "—"
        P(f"{GROUP_KO.get(g, g)} {tf}: {len(acs)}({traded}) | {s['n']} | {wr(s['win'])} | {mn} | {wl} | "
          f"{wr(longs / len(rows)) if rows else '—'} | {'—' if hold is None else f'{hold:.1f}시간'} | "
          f"{up}/{down}/{bust} | {med} | {dd}")

    # ------------------------------------------------------------------ 2. cost split
    P("")
    P("[2. 거래당 비용 분해, 지갑 대비] 가격 움직임 손익(비용 전) | 수수료 | 펀딩 | 순손익 | "
      "가격으론 이겼는데 비용 때문에 진 거래")
    for g, tf in gkeys:
        if hide(g) or g == "extra":
            continue
        rows = [t for ac in groups[(g, tf)] for t in by_acct.get(ac["account_id"], [])]
        if not rows:
            continue
        flipped = sum(t["gross_ret"] > 0 >= t["ret"] for t in rows)
        P(f"{GROUP_KO.get(g, g)} {tf}: {pct(mean(t['gross_ret'] for t in rows))} | "
          f"−{mean(t['fee_ret'] for t in rows) * 100:.2f}% | {pct(-mean(t['fund_ret'] for t in rows), 3)} | "
          f"{pct(mean(t['ret'] for t in rows))} | {flipped}건({flipped / len(rows) * 100:.0f}%)")

    # ------------------------------------------------------------------ 3. against the backtest
    P("")
    P("[3. 5년 백테스트와 비교, 규칙봇 36개] 봉: 지금 거래당 (하루 단위 95% 범위, 날 수) | 백테스트 거래당 | "
      "지금 승률 / 백테스트 승률")
    for tf in CORE_TFS:
        rows = [t for t in core if t["tf"] == tf]
        if not rows:
            continue
        per_day = defaultdict(list)
        for t in rows:
            per_day[day(t["exit_time"])].append(t["ret"])
        dm = [st.mean(v) for v in per_day.values()]
        rg = range95(dm)
        cells = [(k, v) for k, v in BT.items() if k.endswith("@" + tf) and v[0]]
        bn = sum(v[0] for _, v in cells)
        bmean = sum(v[0] * v[2] for _, v in cells) / bn if bn else None
        bwin = sum(v[0] * v[1] for _, v in cells) / bn if bn else None
        s = stats(rows)
        rtxt = "날 수 부족" if rg is None else f"{pct(rg[0])} ~ {pct(rg[1])}"
        P(f"{tf}: {pct(s['mean'])} ({rtxt}, {len(dm)}일) | {pct(bmean)} | {wr(s['win'])} / {wr(bwin)}")
    live_cells, bt_cells = [], []
    better, worse = [], []
    order = sorted((v[2], k) for k, v in BT.items() if v[0] and v[2] is not None)
    half = {k for _, k in order[len(order) // 2:]}
    for ac in accts.values():
        if ac["group"] != "core":
            continue
        k = f"{ac['strategy']}@{ac['timeframe']}"
        rows = by_acct.get(ac["account_id"], [])
        if k in BT and BT[k][0] and rows:
            (better if k in half else worse).extend(rows)
            if len(rows) >= 5:
                live_cells.append(st.mean(t["ret"] for t in rows))
                bt_cells.append(BT[k][2])
    rho = spearman(live_cells, bt_cells)
    P(f"칸별 순위 상관(지금 5건 이상인 {len(live_cells)}칸, 지금 거래당 vs 백테스트 거래당): "
      f"{'—' if rho is None else f'{rho:+.2f}'} (0이면 백테스트 순위가 지금 순위를 못 맞힘, 1이면 그대로)")
    P(f"백테스트 좋은 절반 칸: {len(better)}건 거래당 {pct(mean(t['ret'] for t in better))} · "
      f"나쁜 절반 칸: {len(worse)}건 거래당 {pct(mean(t['ret'] for t in worse))}")
    wl = [t for t in core if t["strategy"] in WATCH_CORE]
    ot = [t for t in core if t["strategy"] not in WATCH_CORE]
    P(f"관찰 후보 8개(지금 숫자): {len(wl)}건 승률 {wr(stats(wl)['win'])} 거래당 {pct(stats(wl)['mean'])} · "
      f"나머지 28개: {len(ot)}건 승률 {wr(stats(ot)['win'])} 거래당 {pct(stats(ot)['mean'])}")

    # ------------------------------------------------------------------ 4. all 36 core strategies
    P("")
    P("[4. 규칙봇 36개 전부] 순위. 매매법 (4개 봉 잔고 합 변화): 봉 거래 승률 거래당 잔고 낙폭 [백테스트 거래당] "
      "· 같은 줄 순서 15m 30m 1h 4h")
    by_strat = defaultdict(list)
    for ac in accts.values():
        if ac["group"] == "core":
            by_strat[ac["strategy"]].append(ac)
    ranked = sorted(by_strat.items(), key=lambda kv: -sum(ac["equity"] - START for ac in kv[1]))
    for i, (name, acs) in enumerate(ranked, 1):
        cells = []
        for ac in sorted(acs, key=lambda ac: tf_key(ac["timeframe"])):
            rows = by_acct.get(ac["account_id"], [])
            b = BT.get(f"{name}@{ac['timeframe']}")
            bt = "—" if not b or not b[0] else pct(b[2], 1)
            if not rows:
                cells.append(f"{ac['timeframe']} 거래 없음 [{bt}]")
                continue
            s = stats(rows)
            dd = "" if ac["max_dd"] is None else f" 낙폭{ac['max_dd'] * 100:.0f}%"
            cells.append(f"{ac['timeframe']} {s['n']}건 {wr(s['win'])} {pct(s['mean'], 1)} "
                         f"${ac['equity']:,.0f}{dd}{' 파산' if ac['bust'] else ''} [{bt}]")
        tot = sum(ac["equity"] - START for ac in acs)
        star = " ★관찰" if name in WATCH_CORE else ""
        P(f"{i}. {name}{star} ({'+' if tot >= 0 else '−'}${abs(tot):,.0f}): " + " · ".join(cells))

    # ------------------------------------------------------------------ 5. all DeepSeek
    P("")
    hdr = "돈 숫자 보임(--ds-money)" if a.ds_money else "두 분 결정(D11)대로 돈 숫자는 가림: 거래·승률·플러스/마이너스·잔고 ↑↓만"
    P(f"[5. 딥시크 44개 전부] {hdr}")
    by_ds = defaultdict(list)
    for ac in accts.values():
        if ac["group"] == "ds200":
            by_ds[ac["strategy"]].append(ac)
    for name in sorted(by_ds, key=lambda n: (-sum(len(by_acct.get(ac["account_id"], [])) for ac in by_ds[n]), n)):
        cells = []
        for ac in sorted(by_ds[name], key=lambda ac: tf_key(ac["timeframe"])):
            rows = by_acct.get(ac["account_id"], [])
            if not rows:
                cells.append(f"{ac['timeframe']} 거래 없음")
                continue
            s = stats(rows)
            if hide("ds200"):
                eq = "파산" if ac["bust"] else ("↑" if ac["equity"] > START else "↓")
                cells.append(f"{ac['timeframe']} {s['n']}건 {wr(s['win'])} {'+' if s['mean'] > 0 else '−'} {eq}")
            else:
                cells.append(f"{ac['timeframe']} {s['n']}건 {wr(s['win'])} {pct(s['mean'], 1)} ${ac['equity']:,.0f}")
        star = " ★관찰" if name in WATCH_DS else ""
        P(f"{name}{star}: " + " · ".join(cells))

    # ------------------------------------------------------------------ 6. reel, flips, extras
    P("")
    P("[6. 5분 단타 · 동전 던지기 · 추가 계좌] 계좌: 거래 승률 거래당 잔고 낙폭")
    for ac in sorted((ac for ac in accts.values() if ac["group"] in ("reel", "flip", "extra")),
                     key=lambda ac: (ac["group"], tf_key(ac["timeframe"]), ac["account_id"])):
        rows = by_acct.get(ac["account_id"], [])
        s = stats(rows)
        dd = "—" if ac["max_dd"] is None else f"{ac['max_dd'] * 100:.0f}%"
        P(f"{ac['account_id']} ({GROUP_KO.get(ac['group'], ac['group'])}): {s['n']}건 {wr(s['win'])} "
          f"{pct(s['mean'], 1)} ${ac['equity']:,.0f} {dd}")

    # ------------------------------------------------------------------ 7. coin x side
    P("")
    P("[7. 코인 × 방향] 코인: 롱 거래 승률 거래당 · 숏 거래 승률 거래당 (규칙봇 36개 | 동전 던지기)")
    flips = [t for t in trades if t["group"] == "flip"]
    for sym in sorted({t["symbol"] for t in core + flips}):
        parts = []
        for rows in (core, flips):
            lo = stats([t for t in rows if t["symbol"] == sym and t["side"] > 0])
            sh = stats([t for t in rows if t["symbol"] == sym and t["side"] < 0])
            parts.append(f"롱 {lo['n']}건 {wr(lo['win'])} {pct(lo['mean'], 1)} · 숏 {sh['n']}건 {wr(sh['win'])} "
                         f"{pct(sh['mean'], 1)}")
        P(f"{sym}: " + " | ".join(parts))

    # ------------------------------------------------------------------ 8. per day
    P("")
    P("[8. 날짜별] 날짜: 코인 하루 움직임 | 규칙봇 롱 / 숏 거래당 | 묶음별 거래 거래당")
    days_all = sorted({day(t["exit_time"]) for t in trades})
    for d in days_all:
        mv = " ".join(f"{sym.replace('USDT', '')} {pct(c / o - 1, 1)}" for (dd_, sym), (o, c) in sorted(moves.items())
                      if dd_ == d and o)
        rows = [t for t in core if day(t["exit_time"]) == d]
        lo = stats([t for t in rows if t["side"] > 0])
        sh = stats([t for t in rows if t["side"] < 0])
        gp = []
        for g in GROUP_KO:
            rg = [t for t in trades if t["group"] == g and day(t["exit_time"]) == d]
            if not rg:
                continue
            m = stats(rg)["mean"]
            gp.append(f"{GROUP_KO[g]} {len(rg)}건 " + (("+" if m > 0 else "−") if hide(g) else pct(m, 1)))
        P(f"{d}: {mv or '코인 움직임 기록 없음'} | 롱 {lo['n']}건 {pct(lo['mean'], 1)} / 숏 {sh['n']}건 "
          f"{pct(sh['mean'], 1)} | " + " · ".join(gp))

    # ------------------------------------------------------------------ 9. exits
    P("")
    P("[9. 청산 이유 × 봉, 규칙봇 36개] 이유 거래(비율) 거래당 평균 보유")
    for tf in CORE_TFS:
        rows = [t for t in core if t["tf"] == tf]
        if not rows:
            continue
        by = defaultdict(list)
        for t in rows:
            by[t["exit_reason"]].append(t)
        P(f"{tf}: " + " · ".join(
            f"{r} {len(v)}({len(v) / len(rows) * 100:.0f}%) {pct(mean(x['ret'] for x in v), 1)} "
            f"{mean(x['hold_h'] for x in v):.1f}시간" for r, v in sorted(by.items(), key=lambda kv: -len(kv[1]))))
    sl = [t for t in core if t["exit_reason"] == "SL" and t["mfe_r"] is not None]
    if sl:
        P(f"손절(SL) {len(sl)}건이 손절 전에 유리하게 간 거리(손절폭 = 1): 중앙 {median(t['mfe_r'] for t in sl):.2f} · "
          f"0.5 이상 {sum(t['mfe_r'] >= 0.5 for t in sl)}건 · 1 이상 {sum(t['mfe_r'] >= 1 for t in sl)}건")
    lk = [t for t in core if t["exit_reason"] == "LOCK"]
    if lk and sl:
        P(f"이긴 잠금(LOCK) 평균 {pct(mean(t['ret'] for t in lk), 1)} 대 손절 평균 {pct(mean(t['ret'] for t in sl), 1)}"
          f" → 본전 승률 {(-mean(t['ret'] for t in sl)) / (mean(t['ret'] for t in lk) - mean(t['ret'] for t in sl)) * 100:.0f}%")

    # ------------------------------------------------------------------ 10. leverage and tier
    P("")
    P("[10. 레버리지 · 등급 × 봉, 규칙봇 36개] 봉: 배수 거래 승률 거래당")
    for tf in CORE_TFS:
        rows = [t for t in core if t["tf"] == tf]
        if not rows:
            continue
        by = defaultdict(list)
        for t in rows:
            by[(t["tier"], t["leverage"])].append(t)
        P(f"{tf}: " + " · ".join(f"{tier} {lv}배 {len(v)}건 {wr(stats(v)['win'])} {pct(stats(v)['mean'], 1)}"
                                 for (tier, lv), v in sorted(by.items(), key=lambda kv: kv[0][1])))

    # ------------------------------------------------------------------ 11. hours and weekdays
    P("")
    P("[11. 들어간 시각(한국 시간) · 요일, 규칙봇 36개] 거래 승률 거래당")
    blocks = defaultdict(list)
    wdays = defaultdict(list)
    for t in core:
        k = dt.datetime.fromtimestamp(t["entry_time"] / 1000, KST)
        blocks[k.hour // 3].append(t)
        wdays[k.weekday()].append(t)
    P("시각: " + " · ".join(f"{b * 3:02d}-{b * 3 + 3:02d}시 {len(v)}건 {wr(stats(v)['win'])} "
                             f"{pct(stats(v)['mean'], 1)}" for b, v in sorted(blocks.items())))
    P("요일: " + " · ".join(f"{WEEKDAY_KO[w]} {len(v)}건 {wr(stats(v)['win'])} {pct(stats(v)['mean'], 1)}"
                             for w, v in sorted(wdays.items())))

    # ------------------------------------------------------------------ 12. signals
    P("")
    P("[12. 신호가 어떻게 됐나] 묶음: 들어감 / 이미 포지션 있어 건너뜀 / 다른 신호에 밀림 / 거절(이유)")
    sig = defaultdict(Counter)
    rej = defaultdict(Counter)
    for o in outcomes:
        g = accts.get(o["account_id"], {}).get("group", "other")
        reason = (o["reason"] or "")[:48]
        if o["status"] == "ENTERED":
            sig[g]["in"] += o["n"]
        elif o["status"] == "SKIPPED" and reason == "in position":
            sig[g]["pos"] += o["n"]
        elif o["status"] == "SKIPPED":
            sig[g]["score"] += o["n"]
        else:
            sig[g]["rej"] += o["n"]
            rej[g][reason] += o["n"]
    for g in GROUP_KO:
        if g not in sig:
            continue
        c = sig[g]
        tot = sum(c.values())
        why = ", ".join(f"{r} {n}" for r, n in rej[g].most_common(4))
        P(f"{GROUP_KO[g]}: 신호 {tot}개 → 들어감 {c['in']}({c['in'] / tot * 100:.0f}%) / 건너뜀 {c['pos']} / "
          f"밀림 {c['score']} / 거절 {c['rej']}{f' ({why})' if why else ''}")

    # ------------------------------------------------------------------ 13. drawdown and open positions
    P("")
    P("[13. 최대 낙폭 · 열린 포지션] 묶음: 낙폭 중앙 / 가장 큰 낙폭 계좌 · 지금 열린 포지션")
    for g in GROUP_KO:
        acs = [ac for ac in accts.values() if ac["group"] == g]
        if not acs:
            continue
        opn = [ac for ac in acs if ac["open"]]
        dds = [(ac["max_dd"], ac["account_id"]) for ac in acs if ac["max_dd"] is not None]
        if hide(g):
            P(f"{GROUP_KO[g]}: 낙폭 가림 · 열린 포지션 {len(opn)}개")
            continue
        unreal = 0.0
        for ac in opn:
            p = ac["open"]
            mk = ac["mark"].get(p.get("symbol"))
            if mk and p.get("qty") and p.get("entry_price"):
                unreal += p["side"] * p["qty"] * (mk - p["entry_price"])
        worst = max(dds) if dds else None
        P(f"{GROUP_KO[g]}: 낙폭 중앙 {median(d for d, _ in dds) * 100:.0f}% / 가장 큰 {worst[0] * 100:.0f}% "
          f"({worst[1]}) · 열린 포지션 {len(opn)}개, 미실현 합 {'+' if unreal >= 0 else '−'}${abs(unreal):,.0f}"
          if dds else f"{GROUP_KO[g]}: 낙폭 기록 없음 · 열린 포지션 {len(opn)}개")

    # ------------------------------------------------------------------ 14. measured costs
    P("")
    P("[14. 실제 호가로 잰 체결 비용, 백테스트 가정 2bp] 코인: 진입 중앙 / 상위10% (건) · 청산 중앙 / 상위10% (건)")
    ok = [f for f in fills if f["ts"] >= d0 and f["slip_best"] is not None and f["status"] == "ok"]
    other = Counter(f["status"] for f in fills if f["ts"] >= d0 and f["status"] != "ok")
    for sym in sorted({f["symbol"] for f in ok}):
        parts = []
        for ev in ("entry", "exit"):
            v = [f["slip_best"] * 10_000 for f in ok if f["symbol"] == sym and f["event"] == ev]
            parts.append(f"{median(v):.1f} / {q90(v):.1f}bp ({len(v)})" if v else "—")
        P(f"{sym}: 진입 {parts[0]} · 청산 {parts[1]}")
    if other:
        P("못 잰 기록: " + ", ".join(f"{k} {n}" for k, n in other.most_common()))

    # ------------------------------------------------------------------ 15. nightly checks
    P("")
    dly = load_daily(a.daily)
    if dly is None:
        P("[15. 서버 밤 점검(daily3.db)] 파일 없음")
    else:
        P("[15. 서버 밤 점검(daily3.db)] 날짜: 다시 돌린 계좌 / 안 맞은 계좌(이른 1분봉, 재시작 틈) | 빠진 1분봉 | "
          "손절 체결 실제-종이 bp 중앙")
        for r in dly["reports"]:
            try:
                rep = json.loads(r["data"])
            except ValueError:
                continue
            par = rep.get("parity")
            if isinstance(par, dict):
                ptxt = (f"{par.get('accounts', '?')} / {par.get('mismatched_accounts', '?')}"
                        f"({par.get('early_kline', 0)}, {par.get('crash_gaps', 0)})")
                grp = par.get("groups") or {}
                bad = [f"{GROUP_KO.get(g, g)} {v.get('mismatched', 0)}" for g, v in grp.items() if v.get("mismatched")]
                if bad:
                    ptxt += " 안 맞음: " + ", ".join(bad)
            else:
                ptxt = str(par)[:60] if par else "—"
            dq = rep.get("data_quality") or {}
            miss = sum(v.get("missing", 0) for v in dq.values() if isinstance(v, dict))
            ss = rep.get("stop_slippage") or {}
            ex = (ss.get("overall") or {}).get("extra_bps_median") if isinstance(ss, dict) else None
            P(f"{r['day']}: {ptxt} | {miss} | {'—' if ex is None else f'{ex:+.1f}bp'}")
        mm = defaultdict(list)
        for m in dly["mismatches"]:
            mm[accts.get(m["account_id"], {}).get("group", "other")].append(m)
        if mm:
            P("안 맞은 계좌 기록: " + " · ".join(f"{GROUP_KO.get(g, g)} {len(v)}건" for g, v in mm.items()))
            for m in [m for g in ("core", "reel", "flip") for m in mm.get(g, [])][:8]:
                try:
                    d = json.loads(m["data"])
                except ValueError:
                    d = {}
                lab = d.get("label") or ("이른 1분봉" if d.get("early_kline") else "")
                P(f"  {m['day']} {m['account_id']}: 실제 {len(d.get('stored', []))}건 / 다시 돌림 "
                  f"{len(d.get('replayed', []))}건 {lab}")
        ss = defaultdict(list)
        for r in dly["stop_slips"]:
            if r["status"] == "ok" and r["real_bps"] is not None and r["paper_bps"] is not None:
                ss[(accts.get(r["account_id"], {}).get("group", "other"), r["exit_reason"])].append(r)
        if ss:
            P("손절·잠금 체결(실제 호가 vs 종이): 묶음 이유: 건 · 종이 중앙 · 실제 중앙 · 실제 상위10% · 차이 합")
            for (g, why), v in sorted(ss.items()):
                diff = sum(r["diff_usd"] or 0 for r in v)
                dtxt = "가림" if hide(g) else f"{'+' if diff >= 0 else '−'}${abs(diff):,.0f}"
                P(f"  {GROUP_KO.get(g, g)} {why}: {len(v)}건 · {median(r['paper_bps'] for r in v):.1f}bp · "
                  f"{median(r['real_bps'] for r in v):.1f}bp · {q90([r['real_bps'] for r in v]):.1f}bp · {dtxt}")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
