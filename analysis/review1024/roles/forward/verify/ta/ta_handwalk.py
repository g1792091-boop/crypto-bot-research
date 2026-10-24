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

trades_csv, siglog_csv, which = sys.argv[1], sys.argv[2], sys.argv[3]
T = pd.read_csv(trades_csv)
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


SL = pd.read_csv(siglog_csv, usecols=["bar_close", "timeframe", "strategy", "symbol", "side", "ref_price", "status"])
SL = SL[SL.timeframe.isin(["30m", "1h", "4h"])]
key = set(zip(SL.bar_close, SL.timeframe, SL.strategy, SL.symbol, SL.side))
rows = []
for q, r in T.iterrows():
    coin = COINS[int(r.coin)]
    g = grid(coin)
    t, tf, side = int(r.t), r.tf, int(r.side)
    e = (t - T0) // MIN
    assert e == r.e
    k = TF_MIN[tf]
    # higher bar judged: the last closed bar at or before t
    h = HTF[tf]
    hb = mybars(g, TF_MIN[h], t - (t - T0) % (TF_MIN[h] * MIN))
    last_close = int(hb.ts.iloc[-1].value // 10**6) + TF_MIN[h] * MIN
    J = TJ.judge_frame(hb, coin, h, rules, fg, pi)
    sb = mybars(g, k, t)
    sp = TJ.spot_frame(sb, tf, fg)
    price = float(sb.close.iloc[-1])
    why, info = TJ.check(rules, r["name"], tf, side, price, J, sp)
    # outcome
    atr_full = mybars(g, k, t, keep=2000)
    atr = float(fg.atr(atr_full, 14).iloc[-1])
    if which == "a2":
        rr, kk, ww = walk(g, e, side, 30.0, None, 2.0 * atr / g["o"][e])
        lev = 30.0
    else:
        rr, kk, ww = walk(g, e, side, 35.0, -0.50, None)
        lev = 35.0
    rows.append({"t": t, "kst": str(kst(t)), "coin": coin, "name": r["name"], "tf": tf, "side": side,
                 "htf": h, "htf_last_close_le_t": last_close <= t, "htf_gap_min": (t - last_close) // MIN,
                 "next_htf_close_after_t": last_close + TF_MIN[h] * MIN > t,
                 "J_dir": J.dir, "J_raw": J.raw, "J_adx": round(J.adx, 2), "tj_dir_table": r.tj_dir_auto,
                 "check_pass": why == "", "why": why[:40], "atr": atr, "p0": g["o"][e],
                 "my_r": rr, "tab_r": r[f"{which}_r"], "my_k": kk, "tab_k": r[f"{which}_k"], "my_why": ww,
                 "tab_why": r[f"{which}_why"], "my_roe": max(lev * rr, -1.0) if np.isfinite(rr) else np.nan,
                 "in_rule_log": (t, tf, r["name"], coin, side) in key})
    drop(coin) if False else None
R = pd.DataFrame(rows)
R.to_csv(f"ta_handwalk_{which}.csv", index=False)
print("n", len(R))
print("htf closed <= t:", R.htf_last_close_le_t.all(), " next htf closes after t:", R.next_htf_close_after_t.all(),
      " htf gap min (should be 0..):", R.htf_gap_min.describe()[["min", "max"]].tolist())
print("judge dir == table dir:", (R.J_dir == R.tj_dir_table).mean(), " check passes (live fn, 300 bars):", R.check_pass.mean())
print(R.loc[~R.check_pass, ["kst", "coin", "name", "tf", "side", "why", "J_dir", "J_adx"]].to_string())
d = (R.my_r - R.tab_r).abs()
print("r max abs diff:", d.max(), " k equal:", (R.my_k == R.tab_k).mean(), " why equal:", (R.my_why == R.tab_why).mean())
print(R.loc[d > 1e-6, ["kst", "coin", "name", "tf", "side", "my_r", "tab_r", "my_k", "tab_k", "my_why", "tab_why"]].to_string())
print("in rule log:", R.in_rule_log.mean(), R.loc[~R.in_rule_log, ["kst", "coin", "name", "tf", "side"]].to_string())
print("mean my_roe:", R.my_roe.mean(), " mean table roe:", (np.maximum(R.tab_r * (30 if which == 'a2' else 35), -1)).mean())
