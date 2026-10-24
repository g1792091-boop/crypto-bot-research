"""The FORWARD tables (live paper period 2026-10-05 18:40 UTC .. 10-24 14:00 UTC), from the bots' own logs:

  forward_rule.csv.gz      every signal the rule bot v4 logged (export current/signal_log.csv, 53,333 rows: SUBMITTED,
                           RECORD = 1d record-only, LATE = > 180 s late, not traded), joined with its paper account's
                           decision (current/outcomes.csv) and, when taken, the paper trade under the HOUSE exits
                           (current/trades.csv: 2 ATR stop, ladder, quality leverage, Binance fees / funding), plus the
                           outcomes RECOMPUTED on the extended 1m grid under the owners' live exits (w35 / w30 / w35s20)
                           and 2 ATR + ladder (a2, 30x) for the signal side and the opposite side (the coin-flip twin),
                           the entry block, and the trend bot's judgments on the last closed 1h / 4h / 1d bars.
  forward_trendbot.csv.gz  every row of the trend bot's paper signal_log (combo/live-ac.db from 10-21 15:00 UTC, and the
                           shadow combo/shadow-trend-wait.db), with the bot's logged judgment next to the recomputed one.
  forward_ac.csv.gz        the same database before the switch (the A+C combined bot, 10-19 .. 10-21 15:00 UTC).
  forward_league.csv.gz    the candidate league's trades (league_exits.db: the league records no per-signal log, only
                           trades and daily counts), with recomputed outcomes and judgments.

Recomputed outcomes: entry at the open of the minute starting at the bar close (e), cost 0.124 % round trip without the
TetherMax payback, funding 0 in October (none published). A trade still open at the extended grid end (2026-10-24
14:12 UTC) has why = 3 ('open', marked at the last close). 5m signals (REEL_H1, RANDOM_* on 5m) and 1d record rows
have no a2 value (a2 is defined on 15m .. 4h bars).

    python3 build_forward.py"""
from common import *
import sqlite3
from frdeep import walk3
from frloss import walk2

TJ_HTF = {"15m": "1h", "30m": "1h", "1h": "4h", "4h": "1d"}      # the trend bot's mapping (15m: as the role map)
TREND_SWITCH = 1792594800000                                      # live-ac.db: first trend-bot row (10-21 15:00 UTC)


def cidx(sym):
    """Index into COINS; -1 for a symbol outside the six (the rule bot also logs XRPUSDT: kept, nothing recomputed)."""
    return COINS.index(sym) if sym in COINS else -1


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)


def role_of():
    R = roles()
    m = {}
    for it in R["items"]:
        m[it["id"]] = it["role"] if it["role"] != "entry" else it["kind"] or "entry"
    for it in R["items"]:
        if it["role"] == "entry":
            for k, v in R["roles"]["entry"].items():
                if it["id"] in v:
                    m[it["id"]] = k
    m["REEL_H1"] = "pullback"
    for k in ("RANDOM_1", "RANDOM_2", "RANDOM_3"):
        m[k] = "flip"
    return m


# ====================================================================== recomputed outcomes
def outcomes(coin_idx, side, e, tf):
    """{w35_r, w35_k, w35_why, ..., *_opp_*} for rows (all of one frame), walking the extended grid per coin."""
    n = len(e)
    out = {}
    for vn in VARIANTS:
        for sfx in ("", "_opp"):
            out[f"{vn}{sfx}_r"] = np.full(n, np.nan)
            out[f"{vn}{sfx}_k"] = np.full(n, -1, np.int64)
            out[f"{vn}{sfx}_why"] = np.full(n, -1, np.int8)
    p0 = np.full(n, np.nan)
    fg = libs()["fg"]
    for ci, coin in enumerate(COINS):
        mc = coin_idx == ci
        if not mc.any():
            continue
        g = grid(coin)
        o, h, l, c = g["o"], g["h"], g["l"], g["c"]
        cumf = np.cumsum(g["fund"])
        ok = mc & (e < g["n"]) & (e > g["first"])
        p0[ok] = o[e[ok]]
        atr = {}
        for t_ in TFS:
            df = bars(coin, t_)
            a = fg.atr(df, 14).to_numpy(float)
            atr[t_] = (close_ms(df, t_), a)
        for sfx, sg in (("", 1), ("_opp", -1)):
            for s in (1, -1):
                m = ok & (side * sg == s)
                if not m.any():
                    continue
                es = e[m]
                for vn, (kind, lev, stop) in VARIANTS.items():
                    if kind == "walk3":
                        a = walk3(o, h, l, c, cumf, es, s, lev, COST, FL, STEP, GAP, stop, 9.0, 0.01, 0, np.zeros(1, bool),
                                  False, c, o, 0.0, g["n"])
                        out[f"{vn}{sfx}_r"][m], out[f"{vn}{sfx}_k"][m], out[f"{vn}{sfx}_why"][m] = a[0], a[1], a[2]
                for t_ in TFS:
                    mt = m & (tf == t_)
                    if not mt.any():
                        continue
                    bc, a_ = atr[t_]
                    t_close = T0 + e[mt].astype(np.int64) * MIN
                    i = np.searchsorted(bc, t_close)
                    good = (i < len(bc)) & (bc[np.minimum(i, len(bc) - 1)] == t_close)
                    av = np.where(good, a_[np.minimum(i, len(bc) - 1)], np.nan)
                    es2 = e[mt]
                    atrd = 2.0 * av / o[es2]
                    fin = np.isfinite(atrd)
                    if not fin.any():
                        continue
                    a = walk2(o, h, l, c, cumf, es2[fin], s, VARIANTS["a2"][1], COST, FL, STEP, GAP,
                              np.ascontiguousarray(atrd[fin]), -1.0, g["n"])
                    idx = np.flatnonzero(mt)[fin]
                    out[f"a2{sfx}_r"][idx], out[f"a2{sfx}_k"][idx], out[f"a2{sfx}_why"][idx] = a[0], a[1], a[2]
        drop(coin)
    out["p0"] = p0
    for k in list(out):
        if k.endswith("_k"):
            out[k] = out[k].astype(np.int32)
    return out


# ====================================================================== judgments from the state tables
_ST = {}


def states(coin, htf):
    key = (coin, htf)
    if key not in _ST:
        z = np.load(os.path.join(OUT, "states", f"{coin}_{htf}.npz"))
        _ST[key] = {k: z[k] for k in z.files if k.startswith("j_") or k in ("ts", "nb")}
    return _ST[key]


def judge_cols(coin_idx, t):
    """j<htf>_* columns: the last closed bar's index, votes, raw3, dir, adx, adx_prev, ema20, atr, close."""
    n = len(t)
    out = {}
    for htf in HTFS:
        cols = {k: np.full(n, np.nan) for k in ("i", "V39", "S6", "OBV", "N12", "raw3", "dir", "adx", "adx_prev", "ema20",
                                                "atr", "close", "bar_close")}
        for ci, coin in enumerate(COINS):
            m = coin_idx == ci
            if not m.any():
                continue
            S = states(coin, htf)
            bc = S["ts"] + TF_MIN[htf] * MIN
            j = last_closed(bc, t[m])
            okj = j >= 1
            jj = np.maximum(j, 1)
            cols["i"][m] = np.where(j >= 0, j, -1)
            for k in ("V39", "S6", "OBV", "N12", "raw3", "dir", "adx", "ema20", "atr", "close"):
                cols[k][m] = np.where(okj, S[f"j_{k}"][jj], np.nan)
            cols["adx_prev"][m] = np.where(okj, S["j_adx"][jj - 1], np.nan)
            cols["bar_close"][m] = np.where(okj, bc[jj], np.nan)
        for k, v in cols.items():
            out[f"j{htf}_{k}"] = v
    return out


def spot_cols(coin_idx, t, tf):
    """The entry bar's EMA20, ATR14, RSI14 (fg, as trendjudge.spot_frame) and range, for the trend bot's checks."""
    fg = libs()["fg"]
    n = len(t)
    out = {k: np.full(n, np.nan) for k in ("spot_ema20", "spot_atr", "spot_rsi", "spot_range", "spot_close")}
    for ci, coin in enumerate(COINS):
        for t_ in TFS:
            m = (coin_idx == ci) & (tf == t_)
            if not m.any():
                continue
            df = bars(coin, t_)
            bc = close_ms(df, t_)
            i = np.searchsorted(bc, t[m])
            good = (i < len(bc)) & (bc[np.minimum(i, len(bc) - 1)] == t[m])
            i = np.minimum(i, len(bc) - 1)
            vals = {"spot_ema20": fg.ema(df["close"], 20).to_numpy(float), "spot_atr": fg.atr(df, 14).to_numpy(float),
                    "spot_rsi": fg.rsi(df["close"], 14).to_numpy(float),
                    "spot_range": (df.high - df.low).to_numpy(float), "spot_close": df.close.to_numpy(float)}
            for k, v in vals.items():
                out[k][m] = np.where(good, v[i], np.nan)
        drop(coin)
    return out


def tj_check(strategy, tf, side, price, J, S, hold_entry, prefix=None):
    """Vectorised paperbot/trendjudge.check (the TrendRules defaults + the 10-22 config): '' = pass, else a reason
    code: hold / against / weak / tired / breakout / far_htf / far_etf / rsi / na. J: judge columns of the higher bar of
    each row (dict of arrays raw3, dir, adx, adx_prev, ema20, atr); S: spot columns."""
    n = len(side)
    why = np.full(n, "", dtype=object)
    d = J["dir"]
    adx, adxp = J["adx"], J["adx_prev"]
    with np.errstate(invalid="ignore", divide="ignore"):
        far_h = side * (price - J["ema20"]) / J["atr"]
        far_e = (price - S["spot_ema20"]) / S["spot_atr"]
        na = ~np.isfinite(d) | ~np.isfinite(adx) | ~np.isfinite(adxp) | ~np.isfinite(far_h) | ~np.isfinite(far_e) \
            | ~np.isfinite(S["spot_rsi"])
        brk = np.isin(strategy, ("F3_BOS", "F15_ORB", "N06_MACD_ORB"))
        rules = [
            ("na", na),
            ("hold", (d == 0) & (not hold_entry)),
            ("against", (d != 0) & (d != side)),
            ("weak", ~(adx >= 20.0)),
            ("tired", (adx > 40.0) & (adx < adxp)),
            ("breakout", brk & ~((adx < 30.0) & (adx > adxp))),
            ("far_htf", far_h > 1.5),
            ("far_etf", np.abs(far_e) > 1.5),
            ("rsi", ((side > 0) & (S["spot_rsi"] >= 70.0)) | ((side < 0) & (S["spot_rsi"] <= 30.0))),
        ]
    for code, cond in rules:
        put = (why == "") & np.asarray(cond, bool)
        why[put] = code
    return why, far_h, far_e


def judge_for_tf(cols, tf):
    """The judge columns of each row's trend-bot higher timeframe (TJ_HTF)."""
    n = len(tf)
    J = {k: np.full(n, np.nan) for k in ("raw3", "dir", "adx", "adx_prev", "ema20", "atr", "i")}
    htf = np.array([TJ_HTF.get(x, "") for x in tf], dtype=object)
    for h in HTFS:
        m = htf == h
        for k in J:
            J[k][m] = cols[f"j{h}_{k}"][m]
    return J, htf


def add_checks(D, price_col="p0"):
    J, htf = judge_for_tf(D, D["tf"].to_numpy())
    S = {k: D[k].to_numpy(float) for k in ("spot_ema20", "spot_atr", "spot_rsi")}
    side = D["side"].to_numpy(float)
    price = D[price_col].to_numpy(float)
    w1, fh, fe = tj_check(D["strategy"].to_numpy(), D["tf"].to_numpy(), side, price, J, S, hold_entry=True)
    w0, _fh, _fe = tj_check(D["strategy"].to_numpy(), D["tf"].to_numpy(), side, price, J, S, hold_entry=False)
    D["tj_htf"] = htf
    D["tj_dir"] = J["dir"]
    D["tj_why_1022"] = w1          # the live config since 10-22 (hold_entry: a 보류 does not stop an entry)
    D["tj_why_1021"] = w0          # the 10-21 config (보류 = no entry)
    D["far_htf_atr"] = fh
    D["far_etf_atr"] = fe
    return D


def common_cols(D):
    """e, blk, outcomes, judges, spot, checks for a frame with t (bar close ms), coin (index), side, tf, strategy."""
    t = D["t"].to_numpy(np.int64)
    ci = D["coin"].to_numpy(np.int64)
    side = D["side"].to_numpy(np.int64)
    tf = D["tf"].to_numpy()
    e = ((t - T0) // MIN).astype(np.int64)
    D["e"] = e
    blk = np.load(os.path.join(OUT, "grid", "blk15.npy"))
    from frcore import blocked
    code = {s: i for i, s in enumerate(BLOCK)}
    j15 = e // 15 - 1
    on15 = (e % 15 == 0) & (j15 >= 0) & (j15 < len(blk))
    D["blk"] = np.where(on15, blk[np.clip(j15, 0, len(blk) - 1)], -1)
    off = np.flatnonzero(~on15)
    for q in off:
        D.iloc[q, D.columns.get_loc("blk")] = code[blocked(int(t[q]))]
    O = outcomes(ci, side, e, tf)
    for k, v in O.items():
        D[k] = v
    for k, v in judge_cols(ci, t).items():
        D[k] = v
    for k, v in spot_cols(ci, t, tf).items():
        D[k] = v
    return add_checks(D)


# ====================================================================== the rule bot
def rule_table():
    s = pd.read_csv(os.path.join(RULE, "current__signal_log.csv"))
    o = pd.read_csv(os.path.join(RULE, "current__outcomes.csv"))
    tr = pd.read_csv(os.path.join(RULE, "current__trades.csv"))
    acc = pd.read_csv(os.path.join(RULE, "current__accounts.csv"))
    grp = dict(zip(acc.account_id, acc.data.map(lambda x: json.loads(x).get("group"))))
    D = pd.DataFrame({"sig_id": s.id, "t": s.bar_close.astype(np.int64), "coin": s.symbol.map(cidx).astype(int),
                      "symbol": s.symbol, "side": s.side.astype(int), "strategy": s.strategy, "tf": s.timeframe,
                      "log_status": s.status, "delay_ms": s.delay_ms, "ref_price": s.ref_price, "atr_logged": s.atr})
    D["t_kst"] = kst(D.t).strftime("%Y-%m-%d %H:%M")
    rmap = role_of()
    D["role"] = D.strategy.map(rmap).fillna("?")
    # the paper account's decision (one outcome row per submitted signal)
    o = o.drop(columns=["symbol"]).rename(columns={"sig_strategy_id": "strategy", "sig_timeframe": "tf", "sig_symbol": "symbol", "sig_side": "side"})
    o["t"] = o.sig_ts.astype(np.int64) + 1
    o = o[["t", "symbol", "tf", "strategy", "side", "account_id", "status", "reason"]].rename(
        columns={"account_id": "acct", "status": "acct_status", "reason": "acct_reason"})
    assert not o.duplicated(["t", "symbol", "tf", "strategy", "side"]).any()
    D = D.merge(o, on=["t", "symbol", "tf", "strategy", "side"], how="left")
    D["acct"] = D.acct.fillna(D.strategy + "@" + D.tf)
    D["group"] = D.acct.map(grp).fillna("record")
    D["taken"] = D.acct_status.eq("ENTERED")
    # the paper trade (house exits) of each taken signal
    tr["t"] = tr.signal_ts.astype(np.int64) + 1
    ctx = tr.context.map(lambda x: json.loads(x) if isinstance(x, str) and x.startswith("{") else {})
    T = pd.DataFrame({"acct": tr.account_id, "t": tr.t, "symbol": tr.symbol, "tr_id": tr.id, "tr_entry_time": tr.entry_time,
                      "tr_entry_price": tr.entry_price, "tr_exit_time": tr.exit_time, "tr_exit_reason": tr.exit_reason,
                      "tr_leverage": tr.leverage, "tr_tier": tr.tier, "tr_margin": tr.margin, "tr_roe": tr.roe,
                      "tr_pnl": tr.pnl, "tr_fees": tr.fees, "tr_funding": tr.funding, "tr_price_move": tr.price_move,
                      "tr_equity_after": tr.equity_after, "tr_lock_roe": tr.lock_roe,
                      "tr_htf_regime": ctx.map(lambda d: d.get("htf_regime")), "tr_regime": ctx.map(lambda d: d.get("regime")),
                      "tr_htf": ctx.map(lambda d: d.get("htf"))})
    assert not T.duplicated(["acct", "t", "symbol"]).any()
    D = D.merge(T, on=["acct", "t", "symbol"], how="left")
    D["tr_open"] = D.taken & D.tr_id.isna()          # entered but not closed at the export (open position)
    D = D.sort_values(["t", "sig_id"]).reset_index(drop=True)
    return common_cols(D)


# ====================================================================== the trend bot / A+C (combo databases)
def combo_rows(path, bot_of):
    con = ro(path)
    rows = con.execute("select id, bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, delay_ms, "
                       "status, data from signal_log order by bar_close, id").fetchall()
    tr = con.execute("select id, account_id, symbol, entry_time, exit_time, exit_reason, leverage, roe, pnl, data "
                     "from trades").fetchall()
    con.close()
    out = []
    for (i, bc, tf, strat, sym, side, atr, ref, reft, dly, st, data) in rows:
        d = json.loads(data)
        tj = (d.get("trend") or {})
        j = tj.get("judge") or {}
        sp = tj.get("spot") or {}
        v = j.get("votes") or {}
        out.append({"row_id": i, "t": int(bc), "tf": tf, "member": strat, "strategy": d.get("strategy") or strat.split("@")[0],
                    "symbol": sym, "coin": cidx(sym), "side": int(side), "status": st, "why": d.get("why") or "",
                    "source": d.get("source"), "score": d.get("score"), "ref_price": ref, "delay_ms": dly,
                    "bot": bot_of(int(bc)),
                    "log_j_bar_close": j.get("bar_close"), "log_j_tf": j.get("tf"), "log_j_raw": j.get("raw"),
                    "log_j_dir": j.get("dir"), "log_j_V39": v.get("V39"), "log_j_S6": v.get("S6"),
                    "log_j_OBV": v.get("OBV"), "log_j_N12": v.get("N12"), "log_j_adx": j.get("adx"),
                    "log_j_adx_prev": j.get("adx_prev"), "log_j_ema20": j.get("ema20"), "log_j_atr": j.get("atr"),
                    "log_j_close": j.get("close"), "log_spot_ema20": sp.get("ema20"), "log_spot_atr": sp.get("atr"),
                    "log_spot_rsi": sp.get("rsi"), "log_spot_range": sp.get("range"), "log_price": tj.get("price"),
                    "log_far_htf_atr": tj.get("far_htf_atr"), "log_far_etf_atr": tj.get("far_etf_atr")})
    D = pd.DataFrame(out)
    T = pd.DataFrame([{"tr_id": a, "tr_acct": b, "symbol": c, "tr_entry_time": e_, "tr_exit_time": x, "tr_exit_reason": r,
                       "tr_leverage": lv, "tr_roe": roe, "tr_pnl": pnl,
                       "t": int(json.loads(dt).get("signal_ts", -2)) + 1, "tr_strategy": json.loads(dt).get("strategy_id")}
                      for (a, b, c, e_, x, r, lv, roe, pnl, dt) in tr if b == "COMBO@mix"])
    if len(T):
        D = D.merge(T, on=["t", "symbol"], how="left", suffixes=("", "_t"))
    D["t_kst"] = kst(D.t).strftime("%Y-%m-%d %H:%M")
    return D


def main():
    t0 = time.time()
    D = rule_table()
    D.to_csv(os.path.join(OUT, "forward_rule.csv.gz"), index=False, float_format="%.8g")
    log("forward_rule", D.shape, f"{time.time() - t0:.0f}s")
    xe = os.path.join(XD, "extra")
    live = os.path.join(xe, "db__paperbot__combo__live-ac.db")
    wait = os.path.join(xe, "db__paperbot__combo__shadow-trend-wait.db")
    A = combo_rows(live, lambda bc: "trend" if bc >= TREND_SWITCH else "ac")
    W = combo_rows(wait, lambda bc: "trend_wait")
    TB = pd.concat([A[A.bot == "trend"], W], ignore_index=True)
    TB = common_cols(TB)
    TB.to_csv(os.path.join(OUT, "forward_trendbot.csv.gz"), index=False, float_format="%.8g")
    AC = common_cols(A[A.bot == "ac"].reset_index(drop=True))
    AC.to_csv(os.path.join(OUT, "forward_ac.csv.gz"), index=False, float_format="%.8g")
    log("trendbot", TB.shape, "ac", AC.shape, f"{time.time() - t0:.0f}s")
    con = ro(os.path.join(XD, "league", "db__league_exits.db"))
    rows = con.execute("select account, exit_time, data from trades").fetchall()
    con.close()
    L = []
    for acct, xt, data in rows:
        d = json.loads(data.replace("NaN", "null"))
        L.append({"acct": acct, "strategy": d["strategy_id"], "symbol": d["symbol"], "coin": cidx(d["symbol"]),
                  "tf": d["timeframe"], "side": int(d["side"]), "t": int(d["signal_ts"]) + 1,
                  "tr_entry_time": d["entry_time"], "tr_entry_price": d["entry_price"], "tr_exit_time": d["exit_time"],
                  "tr_exit_reason": d["exit_reason"], "tr_leverage": d["leverage"], "tr_roe": d["roe"], "tr_pnl": d["pnl"],
                  "tr_style": d.get("strategy_style"), "tr_equity_after": d.get("equity_after")})
    LG = pd.DataFrame(L).sort_values(["t", "acct"]).reset_index(drop=True)
    LG["t_kst"] = kst(LG.t).strftime("%Y-%m-%d %H:%M")
    LG["role"] = LG.strategy.map(role_of()).fillna("?")
    LG = common_cols(LG)
    LG.to_csv(os.path.join(OUT, "forward_league.csv.gz"), index=False, float_format="%.8g")
    log("league", LG.shape, f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
