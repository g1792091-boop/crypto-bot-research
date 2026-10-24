"""Verifier (time-alignment lens), independent of the grid tables:
 1. rebuild bars from the raw 1m grid myself (no common.bars), truncated at the signal close;
 2. the trend judge on the last 300 CLOSED higher bars (paperbot/trendjudge.judge_frame, the live function) and the full
    10-22 entry check (trendjudge.check) on the truncated entry bars -> compare with tj_why_1022 of the sig table;
 3. a2 and w35 outcomes by a plain-python minute walk from the entry minute's open (my own code from the rule text);
 4. the signal exists in the rule bot's own live signal_log (raw export, read as data).
Usage: python3 ta_handwalk.py <trades_csv> <signal_log_csv> <which: a2|w35>"""
import sys, os, json, math
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import *  # noqa
from paperbot import trendjudge as TJ

rules = TJ.TrendRules.from_dict(json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["trend"])
fg, pi = TJ.lib()
HTF = {"30m": "1h", "1h": "4h", "4h": "1d"}
COST_ = 2 * (0.00042 + 0.0002)


def mybars(g, k, t_close, keep=300):
    """Whole bars of k minutes closing at or before t_close (ms), last `keep`, built from the 1m arrays myself."""
    e_end = (t_close - T0) // MIN                      # minute index of the close (exclusive end of the last bar)
    assert e_end % k == 0
    nb = e_end // k
    j0 = max(nb - keep, -(-g["first"] // k))
    rows = []
    for j in range(j0, nb):
        a, b = j * k, (j + 1) * k
        rows.append((T0 + a * MIN, g["o"][a], np.nanmax(g["h"][a:b]), np.nanmin(g["l"][a:b]), g["c"][b - 1],
                     np.nansum(g["v"][a:b])))
    A = np.array(rows)
    return pd.DataFrame({"ts": pd.to_datetime(A[:, 0].astype(np.int64), unit="ms"), "open": A[:, 1], "high": A[:, 2],
                         "low": A[:, 3], "close": A[:, 4], "volume": A[:, 5]})


def lock_of(best):
    ft = 0.10 + 0.02
    if best < ft - 1e-12:
        return None
    return 0.10 + 0.05 * math.floor((best - ft) / 0.05 + 1e-9)


def walk(g, e, side, lev, stop_net=None, atr_dist=None):
    """Plain walk: enter at o[e]; each minute i >= e: stop level (gross return) = nearer of the net-ROE stop / the ATR
    distance / the armed lock; if that minute's adverse extreme reaches it -> exit at the level (or the open if it gapped
    through); then update the best net ROE from that minute's favourable extreme and arm the ladder. Funding 0 (October)."""
    o, h, l = g["o"], g["h"], g["l"]
    p0 = o[e]
    best, lk, i = -9.0, None, e
    n = len(o)
    while i < n:
        lev_stop = (stop_net / lev + COST_) if stop_net is not None else (-1.0 / lev + COST_)
        level = lev_stop
        if atr_dist is not None and -atr_dist > level:
            level = -atr_dist
        if lk is not None and lk / lev + COST_ > level:
            level = lk / lev + COST_
        if side > 0:
            up, dn, op = h[i] / p0 - 1, l[i] / p0 - 1, o[i] / p0 - 1
        else:
            up, dn, op = 1 - l[i] / p0, 1 - h[i] / p0, 1 - o[i] / p0
        if dn <= level:
            fill = min(level, op)
            r = max(fill - COST_, -1.0 / lev)
            return r, i - e, (1 if lk is not None else 0)
        rup = lev * (up - COST_)
        if rup > best:
            best = rup
            lk = lock_of(best)
        i += 1
    return np.nan, n - 1 - e, 3


