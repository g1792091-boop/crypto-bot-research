"""Tables of the five-year runs (PREREG.md): D (current rules per year / half-year / coin / member, costs, exits,
wallet, drawdown, coin-flip band; shadows, maker, fee sensitivity) and C (selection on 2021-2024, confirmation once on
2025-01..2026-09). Output: out/results.json (+ the tables printed)."""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fycommon import *
from paperbot.ladder2 import ComboLadder
import math

RUNS = f"{OUT}/runs"
PREREG = f"{REPO}/research/trendbot/fiveyear/PREREG.md"
MARGIN = 0.4
NDRAW = 1000
SEED = 20261021
SEL = (ms("2021-01-01"), ms("2025-01-01"))
CONF = (ms("2025-01-01"), ms("2026-10-01"))
ALL = (ms("2021-01-01"), ms("2026-10-01"))
C_IDS = ["C0_current", "C1_lev20", "C2_lev10", "C3_lock20", "C4_lock30", "C5_stop35", "C6_lev20_lock20",
         "C7_lev20_lock20_stop35"]
D_IDS = ["C0_current", "D1_time4", "D2_immediate", "D3_vote4", "D4_maker", "S_taker0044_bybit", "S_taker0042_woo"]
REASONS = ["LOCK", "SL", "JUDGE", "REV", "TIME", "LIQ", "END"]


def load(name):
    T = pd.read_csv(f"{RUNS}/{name}_trades.csv.gz")
    T = T.sort_values("entry_t").reset_index(drop=True)
    T["g"] = 1 + MARGIN * T.roe
    T["opp_g"] = 1 + MARGIN * T.opp_roe
    dt = pd.to_datetime(T.entry_t, unit="ms", utc=True)
    T["year"] = dt.dt.year
    T["half"] = dt.dt.year.astype(str) + np.where(dt.dt.month <= 6, "H1", "H2")
    T["win"] = T.roe > 0
    return T


def weekdays(a, b):
    return int(np.busday_count(pd.Timestamp(a, unit="ms").date(), pd.Timestamp(b, unit="ms").date()))


def draws(T):
    """flip[d, i] True: draw d takes the other side on trade i (side random, p = 1/2)."""
    rng = np.random.default_rng(SEED)
    return rng.random((NDRAW, len(T))) < 0.5


def twin_stats(T, flip, mask):
    r = np.where(flip[:, mask], T.opp_roe.to_numpy()[mask], T.roe.to_numpy()[mask])
    lg = np.log(np.clip(1 + MARGIN * r, 1e-12, None)).sum(axis=1)
    mean = r.mean(axis=1) if mask.sum() else np.zeros(NDRAW)
    win = (r > 0).mean(axis=1) if mask.sum() else np.zeros(NDRAW)
    return lg, mean, win


def pct(a):
    return [float(np.percentile(a, q)) for q in (5, 50, 95)]


def block(T, flip, mask, a, b):
    t = T[mask]
    n = int(mask.sum())
    wd = weekdays(a, b)
    out = {"entries": n, "weekdays": wd, "per_weekday": round(n / wd, 3) if wd else None}
    if not n:
        return out
    lg = float(np.log(t.g.clip(lower=1e-12)).sum())
    path = np.cumprod(t.g.to_numpy())
    peak = np.maximum.accumulate(np.concatenate([[1.0], path]))[1:]
    dd = float((1 - path / peak).max())
    tl, tm, tw = twin_stats(T, flip, mask.to_numpy())
    out.update({
        "win_pct": round(100 * t.win.mean(), 1), "roe_mean": float(t.roe.mean()), "roe_median": float(t.roe.median()),
        "pre_mean": float(t.pre.mean()), "pre_win_pct": round(100 * (t.pre > 0).mean(), 1),
        "pre_mean_other_side": float(t.opp_pre.mean()), "roe_mean_other_side": float(t.opp_roe.mean()),
        "zero_cost_log_growth_approx": float(np.log(np.clip(1 + MARGIN * t.pre, 1e-12, None)).sum()),
        "slip_mean": float(t.slip_cost.mean()), "fee_mean": float(t.fee.mean()), "fund_mean": float(t.fund.mean()),
        "lev_mean": float(t.lev.mean()),
        "exits": {r: int((t.reason == r).sum()) for r in REASONS if (t.reason == r).any()},
        "exit_roe_mean": {r: float(t.roe[t.reason == r].mean()) for r in REASONS if (t.reason == r).any()},
        "log_growth": lg, "growth": float(np.exp(lg)), "worst_dd": dd,
        "long_short": [int((t.side > 0).sum()), int((t.side < 0).sum())],
        "twin_growth_5_50_95": [float(np.exp(x)) for x in pct(tl)], "twin_log_growth_5_50_95": pct(tl),
        "twin_roe_mean_5_50_95": pct(tm), "twin_win_pct_5_50_95": [100 * x for x in pct(tw)],
        "rank_vs_twin_pct": float(100 * (tl < lg).mean()),
    })
    return out


def periods():
    ys = [(str(y), ms(f"{y}-01-01"), ms(f"{y + 1}-01-01") if y < 2026 else ms("2026-10-01")) for y in range(2021, 2027)]
    hs = []
    for y in range(2021, 2027):
        hs.append((f"{y}H1", ms(f"{y}-01-01"), ms(f"{y}-07-01")))
        if y < 2026:
            hs.append((f"{y}H2", ms(f"{y}-07-01"), ms(f"{y + 1}-01-01")))
        else:
            hs.append((f"{y}H2(7-9월)", ms(f"{y}-07-01"), ms("2026-10-01")))
    return ys, hs


def describe(name, detail=True):
    T = load(name)
    flip = draws(T)
    ys, hs = periods()
    res = {"name": name, "n": int(len(T))}
    m_all = (T.entry_t >= ALL[0]) & (T.entry_t < ALL[1])
    res["all"] = block(T, flip, m_all, *ALL)
    res["selection_2021_2024"] = block(T, flip, (T.entry_t >= SEL[0]) & (T.entry_t < SEL[1]), *SEL)
    res["confirm_2025_202609"] = block(T, flip, (T.entry_t >= CONF[0]) & (T.entry_t < CONF[1]), *CONF)
    res["years"] = {y: block(T, flip, (T.entry_t >= a) & (T.entry_t < b), a, b) for y, a, b in ys}
    if detail:
        res["halves"] = {h: block(T, flip, (T.entry_t >= a) & (T.entry_t < b), a, b) for h, a, b in hs}
    if detail == "full":
        res["coins"] = {c: block(T, flip, m_all & (T.coin == c), *ALL) for c in COINS}
        res["members"] = {lab: block(T, flip, m_all & (T.label == lab), *ALL) for lab in sorted(T.label.unique())}
        res["coin_year_roe_mean"] = {c: {str(y): float(T.roe[(T.coin == c) & (T.year == y)].mean())
                                         for y in range(2021, 2027) if ((T.coin == c) & (T.year == y)).any()}
                                     for c in COINS}
        res["member_year_roe_mean"] = {lab: {str(y): float(T.roe[(T.label == lab) & (T.year == y)].mean())
                                             for y in range(2021, 2027) if ((T.label == lab) & (T.year == y)).any()}
                                       for lab in sorted(T.label.unique())}
        res["coin_year_n"] = {c: {str(y): int(((T.coin == c) & (T.year == y)).sum()) for y in range(2021, 2027)}
                              for c in COINS}
        res["member_year_n"] = {lab: {str(y): int(((T.label == lab) & (T.year == y)).sum()) for y in range(2021, 2027)}
                                for lab in sorted(T.label.unique())}
        w = 1000 * np.cumprod(T.g.to_numpy())
        q = pd.Series(w, index=pd.to_datetime(T.exit_t, unit="ms", utc=True)).resample("QE").last().ffill()
        res["wallet_quarter_end_usd"] = {str(k.date()): float(v) for k, v in q.items()}
        bust = np.flatnonzero(w < 10)
        res["wallet_below_10usd_first"] = (str(pd.to_datetime(T.exit_t.iloc[bust[0]], unit="ms").date())
                                           if len(bust) else None)
        res["wallet_min_usd"] = float(w.min())
        res["wallet_end_usd"] = float(w[-1])
        res["hold_min_median"] = float(((T.exit_t - T.entry_t) / MIN).median())
        res["hold_min_by_reason_median"] = {r: float(((T.exit_t - T.entry_t) / MIN)[T.reason == r].median())
                                            for r in REASONS if (T.reason == r).any()}
        res["lock_reached"] = T.lock.fillna(-1).round(2).value_counts().sort_index().to_dict()
    return res, T


def ambiguity(T):
    """Stop first inside a 1m bar: exits by stop (SL / LOCK, not at an open gap) whose exit minute also reached a higher
    ladder step (favourable extreme of that minute). The engine's lock applies from the next bar anyway; an executor that
    moves its exchange stop inside the minute could have locked more. Upper bound of the difference."""
    from engine5y import markets, CFG
    lad = ComboLadder.of(CFG["ladder"])
    mk = markets()
    n = amb = 0
    gain = []
    rt = 2 * (0.0005 + 0.0002)
    for r in T[T.reason.isin(["SL", "LOCK"])].itertuples():
        M = mk[r.coin]
        x = (int(r.exit_t) - T0) // MIN
        if abs(float(M.o[x]) - r.X_ref) < 1e-12 * r.X_ref:
            continue                          # gap at the open: no ambiguity
        n += 1
        fill = r.ref * (1 + r.side * 0.0002)
        ext = float(M.h[x]) if r.side > 0 else float(M.l[x])
        best = r.lev * (r.side * (ext / fill - 1) - rt - r.fund / r.lev)
        lk = lad.lock_for(best)
        cur = -1.0 if pd.isna(r.lock) else r.lock
        if lk is not None and lk > cur + 1e-9:
            amb += 1
            gain.append(lk - r.roe)
    return {"stop_exits_inside_bar": n, "same_minute_reached_higher_step": amb,
            "share_pct": round(100 * amb / max(1, n), 1),
            "roe_gain_if_locked_first_mean_over_all_trades": float(np.sum(gain) / max(1, len(T))),
            "roe_gain_sum": float(np.sum(gain))}


def funnel(name):
    c = pd.read_csv(f"{RUNS}/{name}_cand.csv.gz")
    c["year"] = pd.to_datetime(c.t0, unit="ms", utc=True).dt.year
    st = c.stage.fillna("")
    stage = np.select([st.str.startswith("x_when"), st.str.startswith("x_block:"), st.str.startswith("x_nojudge"),
                       st.str.startswith("x_check"), st.str.startswith("x_no_pullback"),
                       st.str.startswith("x_block_at_entry"), st.str.startswith("x_skip_in_position"),
                       st.str.startswith("x_skip_lower"), st == "entered"],
                      ["when", "block", "nojudge", "check", "no_pullback", "block_at_entry", "in_position",
                       "lower_score", "entered"], "other")
    c["s"] = stage
    blocks = c[st.str.startswith("x_block:")].stage.str.split(":").str[1].value_counts().to_dict()
    tab = c.groupby(["year", "s"]).size().unstack(fill_value=0)
    return {"by_year": {str(y): {k: int(v) for k, v in r.items()} for y, r in tab.iterrows()}, "blocks": blocks,
            "total": {k: int(v) for k, v in c.s.value_counts().items()}}


def main():
    out = {"prereg_sha256": sha256(PREREG), "data_sha256": {c: sha256(f"{FG}/1m/{c}.npz") for c in COINS},
           "signal_agreement": json.load(open(f"{OUT}/signal_agreement.json")),
           "judge_agreement": json.load(open(f"{OUT}/judge_agreement.json")),
           "validate_vs_earlier_replay": json.load(open(f"{OUT}/validate.json")),
           "engine_vs_repo_TrendEngine": json.load(open(f"{OUT}/engine_check.json")),
           "twin": {"draws": NDRAW, "seed": SEED, "margin": MARGIN}}
    D = {}
    for name in D_IDS:
        r, T = describe(name, detail="full" if name == "C0_current" else "halves")
        D[name] = r
        if name == "C0_current":
            out["ambiguity_stop_first_C0"] = ambiguity(T)
            out["funnel_C0"] = funnel(name)
        if name == "D4_maker":
            out["ambiguity_stop_first_D4"] = ambiguity(T)
            fm = T[(T.entry_t // MIN) == (T.exit_t // MIN)]
            out["maker_stopped_in_fill_minute"] = int(len(fm))
    out["D"] = D
    C = {}
    for name in C_IDS:
        r, _ = describe(name, detail=False)
        C[name] = {k: r[k] for k in ("n", "all", "selection_2021_2024", "confirm_2025_202609", "years")}
    sel = {k: C[k]["selection_2021_2024"]["log_growth"] for k in C_IDS}
    best = max(C_IDS, key=lambda k: (sel[k], -C_IDS.index(k)))
    cf = C[best]["confirm_2025_202609"]
    c0 = C["C0_current"]["confirm_2025_202609"]
    out["C"] = {"variants": C, "selection_metric": sel, "selected": best,
                "confirm": {"selected": best, "log_growth": cf["log_growth"], "growth": cf["growth"],
                            "C0_log_growth": c0["log_growth"], "C0_growth": c0["growth"],
                            "better_than_current": (cf["log_growth"] > c0["log_growth"]) if best != "C0_current" else None,
                            "twin_log_growth_95": cf["twin_log_growth_5_50_95"][2],
                            "better_than_luck": cf["log_growth"] > cf["twin_log_growth_5_50_95"][2]}}
    def rnd(x):
        if isinstance(x, float):
            return float(f"{x:.6g}") if math.isfinite(x) else None
        if isinstance(x, dict):
            return {str(k): rnd(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [rnd(v) for v in x]
        if isinstance(x, (np.floating,)):
            return rnd(float(x))
        if isinstance(x, (np.integer,)):
            return int(x)
        if isinstance(x, (np.bool_,)):
            return bool(x)
        return x
    json.dump(rnd(out), open(f"{OUT}/results.json", "w"), indent=1, default=str, ensure_ascii=False)
    print("selected", best, json.dumps(out["C"]["confirm"], indent=1))


if __name__ == "__main__":
    main()
