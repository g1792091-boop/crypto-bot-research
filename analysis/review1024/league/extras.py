"""More reads for the league review (owners' 10/24 evening requests): conditional reads with a first-half pick and a second-half
check, the 'goal path' (+500 % in 30 days), flat exports for cross-bot work, and a read of every non-trade record in the export.
Used by analyze.py; nothing here writes outside the output folders it is given."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import lg_lib as L

GOAL = 6.0                     # +500 % = x6
HORIZON_DAYS = 30
N_PATHS = 4000
SETTINGS = [(0.40, 30), (0.40, 40), (0.40, 50)]          # the owners' usual: margin 40 % of the wallet, 30 / 40 / 50x
COND_DIMS = [("side_ko", "방향"), ("symbol", "코인"), ("session", "시간대(한국)"), ("g1_ko", "BTC 4시간 추세"),
             ("g2_ko", "변동성"), ("wk_ko", "평일/주말")]


# ------------------------------------------------------------------------------------------------ conditional reads
def cond_block(t: pd.DataFrame, acc: pd.DataFrame, start: int, done: int, min_total: int = 10, min_cell: int = 5) -> dict:
    """For every account with >= min_total trades: each condition cell (side, coin, KST session, BTC trend agreement, volatility,
    weekday/weekend) is read in the FIRST half; a cell with >= min_cell trades and a positive mean wallet % is 'picked' (rule
    fixed before the second half is looked at) and then checked in the SECOND half. The same pick-and-check on the coin-flip
    accounts (-fqc, -ldc) is the luck reference: their direction is random, so whatever 'holds up' there is not skill."""
    t = t.copy()
    t["g1_ko"] = np.where(t["g1"].astype(bool), "추세와 같은 방향", "추세와 반대")
    t["g2_ko"] = np.where(t["g2"].astype(bool), "변동성 보통", "너무 조용/거침")
    mid = (start + done) / 2
    t["half"] = np.where(t["exit_time"] < mid, 1, 2)
    big = set(acc.loc[acc["n"].fillna(0) >= min_total, "account"])
    rows = []
    for a, g in t[t["account"].isin(big)].groupby("account"):
        sfx = g["suffix"].iloc[0]
        h2_all = g.loc[g["half"] == 2, "wallet_ret"]
        for dim, dim_ko in COND_DIMS:
            for k, c in g.groupby(dim):
                c1, c2 = c[c["half"] == 1], c[c["half"] == 2]
                rows.append({"account": a, "pick": g["pick"].iloc[0], "suffix": sfx, "coin_twin": sfx in ("fqc", "ldc"), "dim": dim_ko, "cell": str(k),
                             "n1": int(len(c1)), "m1": float(c1["wallet_ret"].mean()) if len(c1) else None,
                             "p1": float(c1["pnl"].sum()), "n2": int(len(c2)),
                             "m2": float(c2["wallet_ret"].mean()) if len(c2) else None, "p2": float(c2["pnl"].sum()),
                             "acct_m2": float(h2_all.mean()) if len(h2_all) else None})
    df = pd.DataFrame(rows)
    out = {"min_total": min_total, "min_cell": min_cell, "accounts": int(df["account"].nunique()) if len(df) else 0, "cells": int(len(df))}
    if not len(df):
        return out
    picked = df[(df["n1"] >= min_cell) & (df["m1"] > 0)]
    chk = picked[picked["n2"] > 0]

    def summ(x):
        if not len(x):
            return {"picked": 0}
        return {"picked": int(len(x)), "checked": int(len(x)), "held": int((x["m2"] > 0).sum()), "held_share": float((x["m2"] > 0).mean()),
                "m1": float(x["m1"].mean()), "m2": float(x["m2"].mean()), "p2_sum": float(x["p2"].sum()),
                "beats_account_h2": float((x["m2"] > x["acct_m2"]).mean())}
    out["real"] = summ(chk[~chk["coin_twin"]])
    out["coin"] = summ(chk[chk["coin_twin"]])
    # kinds of one pick share its signals: the same cell shows up in several accounts with the same trades. Counted once:
    dd = chk.assign(k1=chk["n1"].astype(str) + "/" + chk["p1"].round(2).astype(str) + "/" + chk["n2"].astype(str) + "/" + chk["p2"].round(2).astype(str))
    dd = dd.drop_duplicates(["pick", "dim", "cell", "coin_twin", "k1"])
    out["real_unique"] = summ(dd[~dd["coin_twin"]])
    out["coin_unique"] = summ(dd[dd["coin_twin"]])
    out["real_never_traded_h2"] = int((~picked["coin_twin"] & (picked["n2"] == 0)).sum())
    by_dim = []
    for dim_ko in [d[1] for d in COND_DIMS]:
        x = chk[(chk["dim"] == dim_ko) & ~chk["coin_twin"]]
        y = chk[(chk["dim"] == dim_ko) & chk["coin_twin"]]
        xu = dd[(dd["dim"] == dim_ko) & ~dd["coin_twin"]]
        by_dim.append({"dim": dim_ko, "real": summ(x), "coin": summ(y), "real_unique": summ(xu)})
    out["by_dim"] = by_dim
    top = chk[~chk["coin_twin"]].sort_values("m1", ascending=False).head(25)
    out["top"] = top[["account", "dim", "cell", "n1", "m1", "p1", "n2", "m2", "p2"]].to_dict("records")
    # cells good in BOTH halves (>= min_cell each): what an honest search would still show, and how many coin cells do the same
    both = df[(df["n1"] >= min_cell) & (df["n2"] >= min_cell) & (df["m1"] > 0) & (df["m2"] > 0)]
    elig_r = df[(df["n1"] >= min_cell) & (df["n2"] >= min_cell) & ~df["coin_twin"]]
    elig_c = df[(df["n1"] >= min_cell) & (df["n2"] >= min_cell) & df["coin_twin"]]
    out["both_halves"] = {"real": int((~both["coin_twin"]).sum()), "real_of": int(len(elig_r)),
                          "coin": int(both["coin_twin"].sum()), "coin_of": int(len(elig_c))}
    out["both_list"] = both[~both["coin_twin"]].sort_values("m2", ascending=False).head(25)[
        ["account", "dim", "cell", "n1", "m1", "n2", "m2", "p1", "p2"]].to_dict("records")
    out["_df"] = df
    return out


# ------------------------------------------------------------------------------------------------ goal path
MMR = 0.005                    # maintenance margin share of the notional used for the liquidation distance (about Binance's small tiers)


def liquidated(adv, lev: float):
    """A trade whose worst move against it (adv, share of the entry price) reaches 1/lev - MMR is liquidated at that leverage."""
    return adv >= (1.0 / lev - MMR)


def simulate(x_days: list, margin: float, lev: float, n_paths: int = N_PATHS, horizon: int = HORIZON_DAYS, seed: int = L.SEED) -> dict:
    """x_days: per day of the record, the list of each trade's (net return per unit of notional = pnl / notional, worst move
    against it as a share of the entry price), in time order. A path draws ``horizon`` days with replacement and applies every
    trade at margin share ``margin`` and leverage ``lev``: wallet x (1 + margin * max(lev * x, -1)), and x (1 - margin) when the
    worst move would have liquidated it at that leverage (isolated margin: one trade loses at most its margin). Returns the
    share of paths that reach x6 within the horizon, that fall to 0.5 or 0.1 before reaching x6, and the end multiples.
    What it cannot see: at another leverage the ladder locks (set in ROE) sit at other prices, so the exits themselves would
    move; that is why this is a rough guide, not a backtest."""
    rng = np.random.default_rng(seed)
    k = len(x_days)
    width = max(1, max(len(v) for v in x_days))
    fac = np.ones((k, width))                        # a day with fewer trades is padded with 'no trade' (factor 1)
    for i, v in enumerate(x_days):
        for j, (x, adv) in enumerate(v):
            fac[i, j] = 1 - margin if liquidated(adv, lev) else 1 + margin * max(lev * x, -1.0)
    idx = rng.integers(0, k, size=(n_paths, horizon))
    f = fac[idx].reshape(n_paths, horizon * width)
    eq = np.cumprod(f, axis=1)
    big = horizon * width + 1

    def first(mask):
        return np.where(mask.any(1), mask.argmax(1), big)
    g, h, tth = first(eq >= GOAL), first(eq <= 0.5), first(eq <= 0.1)
    ends = eq[:, -1]
    return {"p_goal": float((g < big).mean()), "p_half_first": float((h < g).mean()), "p_tenth_first": float((tth < g).mean()),
            "median": float(np.median(ends)), "p05": float(np.quantile(ends, 0.05)), "p95": float(np.quantile(ends, 0.95))}


def kelly(x: np.ndarray, adv: np.ndarray, margin: float = 0.4, max_lev: float = 125) -> tuple:
    """The leverage (at this margin share) that maximises the mean log growth per trade on these trades, and that growth."""
    best = (0.0, 0.0)
    for lev in np.arange(1, max_lev + 1, 1.0):
        r = np.where(liquidated(adv, lev), -margin, margin * np.maximum(lev * x, -1.0))
        gr = np.log(np.maximum(1 + r, 1e-12)).mean()
        if gr > best[1]:
            best = (float(lev), float(gr))
    return best


def goal_block(t: pd.DataFrame, acc: pd.DataFrame, start: int, done: int, accounts: list, min_n: int = 10) -> dict:
    days = list(range(int(start // L.DAY_MS * L.DAY_MS), int(done), L.DAY_MS))
    period = (done - start) / L.DAY_MS
    rows = []
    for a in accounts:
        g = t[t["account"] == a].sort_values("exit_time")
        if len(g) < min_n:
            continue
        x = (g["pnl"] / g["notional"]).values
        adv = np.maximum(0.0, -g["side"].values * (g["mae_price"].values / g["entry_price"].values - 1))
        xd = [list(zip(x[g["day"].values == d], adv[g["day"].values == d])) for d in days]
        r = {"account": a, "n": int(len(g)), "per_day": len(g) / period, "mean_x": float(x.mean()),
             "mean_wallet": float(g["wallet_ret"].mean()), "mean_roe": float(g["roe"].mean()), "small": len(g) < 30,
             "lev_now": float(g["leverage"].mean())}
        # x6 in 30 days needs a mean log growth per trade of ln 6 / (trades in 30 days)
        n30 = r["per_day"] * HORIZON_DAYS
        r["need_log_per_trade"] = float(np.log(GOAL) / n30) if n30 > 0 else None
        kl, kg = kelly(x, adv)
        r["worst_adv"] = float(adv.max())
        r["liq_lev"] = float(1.0 / (adv.max() + MMR)) if adv.max() > 0 else None   # the lowest leverage that liquidates its worst trade
        r["kelly_lev"], r["kelly_log"] = kl, kg
        r["kelly_30d_median_mult"] = float(np.exp(kg * n30)) if kg > 0 else None
        sims = {}
        for m, lev in SETTINGS:
            sims[f"{int(m * 100)}%x{lev}"] = simulate(xd, m, lev, seed=L.SEED + int(lev))
        if kl > 0:
            sims["kelly"] = simulate(xd, 0.4, kl, seed=L.SEED + 7)
        # the leverage (40 % margin) whose median path reaches x6: only when the per-trade mean is positive
        need = None
        if x.mean() > 0 and kg > 0:
            for lev in (60, 75, 100, 125):
                s = simulate(xd, 0.4, lev, n_paths=1000, seed=L.SEED + lev)
                if s["median"] >= GOAL:
                    need = {"lev": lev, **s}
                    break
        r["sims"], r["need"] = sims, need
        # without the luck: the wallet exposure (margin share x leverage) whose AVERAGE path gives x6 in 30 days, ln 6 / (mean x * trades)
        if x.mean() > 0 and n30 > 0:
            r["need_exposure_mean"] = float(np.log(GOAL) / (x.mean() * n30))
            r["need_lev_at40"] = r["need_exposure_mean"] / 0.4
        rows.append(r)
    return {"rows": rows, "goal": GOAL, "horizon": HORIZON_DAYS, "paths": N_PATHS, "settings": [f"{int(m * 100)}%x{lev}" for m, lev in SETTINGS]}


# ------------------------------------------------------------------------------------------------ flat exports
def write_exports(t: pd.DataFrame, acc: pd.DataFrame, start: int, done: int, folder: str) -> dict:
    tn = pd.DataFrame({"account_id": t["account"], "strategy": t["strategy"], "timeframe": t["tf"], "symbol": t["symbol"],
                       "side": t["side"].astype(int), "entry_ms": t["entry_time"].astype("int64"), "exit_ms": t["exit_time"].astype("int64"),
                       "entry_price": t["entry_price"], "exit_price": t["exit_price"], "pnl": t["pnl"], "return_on_margin": t["roe"],
                       "leverage": t["leverage"], "exit_reason": t["exit_reason"]}).sort_values(["exit_ms", "account_id"])
    p1 = os.path.join(folder, "trades_norm.csv")
    tn.to_csv(p1, index=False, float_format="%.10g")
    kd = pd.to_datetime(t["exit_time"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.strftime("%Y-%m-%d")
    dd = t.assign(day_kst=kd).groupby(["account", "day_kst"]).agg(pnl=("pnl", "sum"), trades=("pnl", "size")).reset_index()
    d0 = pd.Timestamp(start, unit="ms", tz="UTC").tz_convert("Asia/Seoul").normalize()
    d1 = pd.Timestamp(done, unit="ms", tz="UTC").tz_convert("Asia/Seoul").normalize()
    all_days = [d.strftime("%Y-%m-%d") for d in pd.date_range(d0, d1, freq="D")]
    grid = pd.MultiIndex.from_product([sorted(acc["account"]), all_days], names=["account", "day_kst"])
    dd = dd.set_index(["account", "day_kst"]).reindex(grid, fill_value=0).reset_index()
    dd = dd.rename(columns={"account": "account_id"})
    dd["trades"] = dd["trades"].astype(int)
    p2 = os.path.join(folder, "daily_pnl.csv")
    dd.to_csv(p2, index=False, float_format="%.10g")
    return {"trades_norm": p1, "daily_pnl": p2, "trades_rows": int(len(tn)), "daily_rows": int(len(dd)), "days": all_days}


# ------------------------------------------------------------------------------------------------ the export's other records
def records_block(base: str, snap: dict, tele: dict, rules: dict, cands: dict, env: dict) -> dict:
    """What every non-trade record in the export holds, with its headline numbers (read-only)."""
    out = []

    def add(key, what, shows, numbers=None):
        out.append({"key": key, "what": what, "shows": shows, "numbers": numbers or {}})
    s = snap or {}
    add("env (etc/candleague_env_safe.txt)", "서버 설정 중 비밀이 아닌 줄", "리그가 어느 기록 파일 · 시작 시각 · 시작 금액 · 최소 배수로 도는지",
        {k: v for k, v in env.items()})
    add("rules.json", "계좌 종류 26개의 청산 규칙", "판정 규칙은 이 파일이 아니라 코드(candleague/summary.py)에 있음. 파일에는 종류마다 청산·손절 한도·필터·동전 짝만",
        {"kinds": len(rules.get("owner_exits", [])), "enabled": rules.get("enabled")})
    bands = {}
    for cid, c in cands.items():
        b = (c.get("source") or {}).get("band") or {}
        if b:
            bands[cid] = {k: v.get("p5") for k, v in b.items()}
    add("candidates.json", "후보 49개의 커스텀값 · 원래 청산 · 5년 출처", "관찰 후보 38개는 5년 시험 성적과 '예상 범위(밴드)'가 있고, 약한 단서 11개는 없음. 딥시크는 금액 없음",
        {"candidates": len(cands), "with_band": len(bands)})
    j = s.get("judge") or {}
    add("league.json · judge (경고등)", "지금 청산(-e) 계좌가 5년 예상 범위(밴드) 하위 5%보다 나쁜지",
        "거래 10번 전에는 '판단 안 함'. 지금 청산 계좌는 손절이 넓어 30배에서 대부분 진입 거절 → 49개 모두 '판단 안 함'",
        {"verdicts": pd.Series([v.get("verdict") for v in j.values()]).value_counts().to_dict() if j else {},
         "max_trades": max([v.get("trades", 0) for v in j.values()] or [0])})
    w = s.get("watch") or {}
    add("league.json · watch", "옛 관찰 리그(10/11)의 점검(11/11·12/11) 구조", "이 청산 리그에서는 점검 날짜 없음(checkpoints 비어 있음). 종류별 거래·승률·평균만 묶음별로",
        {"checkpoints": len(w.get("checkpoints") or [])})
    d = s.get("decision") or {}
    add("league.json · decision (판정)", "미리 정한 판정 4개(빠른 손절 vs 대조, 동전 짝 2개, BTC 필터)와 탐색 8개", d.get("summary_ko", ""),
        {"days": d.get("days"), "counts": d.get("counts"), "min_pairs": d.get("min_pairs")})
    p = s.get("pairs") or {}
    add("league.json · pairs (같은 신호 짝)", "메인 6종을 대조(-ld)와 같은 신호끼리 비교", "같은 신호에서 ROE가 0.05점 넘게 다른 거래의 수와 평균 차이",
        {k: {"n": v.get("n"), "better": v.get("better"), "worse": v.get("worse"), "mean_diff_roe": v.get("mean_diff_roe")}
         for k, v in (p.get("by_role") or {}).items()})
    ev = s.get("events") or []
    evs = {}
    for e in ev:
        key = f"{e.get('role')}:{e.get('event')}"
        x = evs.setdefault(key, {"n": 0, "better": 0, "diff": 0.0})
        x["n"] += 1
        if e.get("roe") is not None and e.get("control_roe") is not None:
            x["diff"] += float(e["roe"]) - float(e["control_roe"])
            x["better"] += float(e["roe"]) > float(e["control_roe"]) + 0.0005
    for x in evs.values():
        x["mean_diff"] = x["diff"] / x["n"] if x["n"] else None
    add("league.json · events (발동 기록)", "규칙 청산 · 손절 좁힘 · 스위칭이 실제로 일어난 최근 200건과 같은 거래의 대조 결과",
        "규칙이 발동한 거래에서 대조보다 나았는지(최근 200건만)", evs)
    ms = s.get("monthsim") or {}
    add("league.json · monthsim (한 달 시뮬)", "지금까지의 날들을 섞어 30일을 만들어 본 결과(종류별 계좌 평균)", ms.get("headline_ko", ""),
        {k.get("suffix"): {"median": (k.get("percentiles") or {}).get("p50"), "p_x4": k.get("p_x4"), "p_below_half": k.get("p_below_half"),
                           "p_real_beats_coin": (k.get("edge_vs_coin") or {}).get("p_real_beats_coin")} for k in ms.get("kinds", [])})
    for key, what in (("risk", "포지션 몰림 · 최악 거래 · 연패"), ("losses", "진 거래의 유형(손실 해부)"), ("costs", "수수료 · 미끄러짐 · 펀딩"),
                      ("signals", "최근 진입"), ("coins", "코인별 성적과 동전 짝 비교")):
        b = s.get(key) or {}
        add(f"league.json · {key}", what, b.get("headline_ko", ""))
    c = s.get("conditions") or {}
    add("league.json · conditions (조건별)", "요일·시간대·방향·코인·봉·BTC 추세·변동성별로 빠른 손절·대조를 동전 짝과 비교(탐색용)", c.get("headline_ko", ""),
        {"cells": c.get("n_cells"), "good": c.get("n_good"), "bad": c.get("n_bad"), "expected_lucky": c.get("expected_lucky")})
    tl = s.get("timeline") or {}
    add("league.json · timeline", "기록된 일(시작 · 첫 거래 · 가장 큰 손익 · 판정 날짜)", tl.get("headline_ko", ""),
        {"rows": [r.get("text_ko") for r in (tl.get("rows") or [])][:12]})
    dq = s.get("dataq") or {}
    add("league.json · dataq (기록 점검)", "엔진이 언제까지 계산했나, 오류 · 빈 잔고 · 이상한 거래 시각", dq.get("headline_ko", ""),
        {"status": dq.get("status"), "counts": dq.get("counts")})
    sv = s.get("server") or {}
    add("league.json · server", "서버 부하 · 엔진 메모리 · 한 번 처리 시간", "", sv)
    tj = os.path.join(base, "snap", "trades.json")
    if os.path.exists(tj):
        T = L.read_json(tj)
        n_tr = sum(len((v or {}).get("trades") or []) for v in T.values())
        pnl_tr = sum(float(x.get("pnl") or 0) for v in T.values() for x in ((v or {}).get("trades") or []))
        add("snap/trades.json", "대시보드가 읽는 계좌별 거래 목록과 잔고 흐름(계좌마다 최근 200번까지)",
            "기록 파일(DB)의 거래와 같은지 확인용", {"accounts": len(T), "trades": n_tr, "pnl_sum": round(pnl_tr, 2)})
    msgs = (tele or {}).get("messages") or []
    kinds = pd.Series([m.get("kind") for m in msgs]).value_counts().to_dict() if msgs else {}
    add("telegram.json", "리그가 보낸 텔레그램 메시지 기록", "아침 요약 말고 다른 알림(파산 · 경고등 · 엔진 멈춤)이 있었는지",
        {"messages": len(msgs), "kinds": kinds, "first": L.kst(msgs[0].get("ms")) if msgs else None, "last": L.kst(msgs[-1].get("ms")) if msgs else None,
         "last_text": msgs[-1].get("text") if msgs else None})
    return {"rows": out}
