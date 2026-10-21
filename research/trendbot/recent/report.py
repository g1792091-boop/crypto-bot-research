"""Summaries of the sim.py runs: per variant and cost set, the trades entered in the KST window 07-01..10-20.
Every trade is re-costed from its reference prices (entry_ref, exit_ref) and order kinds (taker: fee + slippage,
maker: maker fee, no slippage); the paper cost set reproduces sim.py's own net ROE (checked).
Run: python3 -I report.py ROOT OUTDIR TAG [TAG ...]  -> OUTDIR/results.json, tables printed (markdown)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import np, pd  # noqa: E402
import json  # noqa: E402

ROOT, OUTDIR, TAGS = sys.argv[1], sys.argv[2], sys.argv[3:]
IN = f"{ROOT}/out/recent"
KST = 9 * 3_600_000
DAY = 86_400_000
MARGIN, W0 = 0.4, 1000.0
# per side. paper = the bot's own (paperbot/config.py Binance VIP0: taker 0.05 %, maker 0.02 %, slippage 0.02 %);
# bybit = the taker measured on the account 10-20 (deploy/executor.live-*.json net_costs, docs/live15-own-ladder-ko.md)
#         and the maker 0.02 % (research/live15/precheck.py: "measured on the accounts (10-20) and the exchanges' API
#         fee pages"); wooxpro = TetherMax taker 0.042 % (docs/wooxpro-ko.md); its maker is NOT in the repo: 0.02 %
#         assumed. Slippage 0.02 % per taker side everywhere (an assumption, never measured here).
COSTS = {"paper": {"taker": 0.0005, "maker": 0.0002, "slip": 0.0002},
         "bybit": {"taker": 0.00044, "maker": 0.0002, "slip": 0.0002},
         "wooxpro": {"taker": 0.00042, "maker": 0.0002, "slip": 0.0002}}
HALF = int(pd.Timestamp("2026-08-25 15:00", tz="UTC").value // 10**6)       # KST 08-26 00:00: two halves of the window


def recost(side, lev, eref, ekind, xref, xkind, c):
    side, lev = np.asarray(side, float), np.asarray(lev, float)
    ein = np.asarray(ekind) == "taker"
    xin = np.asarray(xkind) == "taker"
    fin = np.where(ein, eref * (1 + side * c["slip"]), eref)
    fout = np.where(xin, xref * (1 - side * c["slip"]), xref)
    fee_in = np.where(ein, c["taker"], c["maker"])
    fee_out = np.where(xin, c["taker"], c["maker"])
    move = lev * side * (fout / fin - 1)
    roe = move - lev * (fee_in + fee_out * fout / fin)
    roe = np.where(move < -1, -1 - lev * fee_in, roe)                                   # liquidated (none expected)
    before = lev * side * (xref / eref - 1)
    return roe, before, before - move, lev * (fee_in + fee_out * fout / fin)


def wallet_stats(roe):
    w = W0 * np.cumprod(1 + MARGIN * np.asarray(roe))
    path = np.concatenate([[W0], w])
    peak = np.maximum.accumulate(path)
    dd = 1 - path / peak
    run = best = 0
    for r in roe:
        run = run + 1 if r < 0 else 0
        best = max(best, run)
    return {"end": round(float(path[-1]), 1), "low": round(float(path.min()), 1), "high": round(float(path.max()), 1),
            "worst_drawdown": round(float(dd.max()), 3), "longest_losing_run": int(best)}


def weekdays():
    days = pd.date_range("2026-07-01", "2026-10-20", freq="D")
    return int((days.dayofweek < 5).sum())


NWD = weekdays()
res = {"what": "추세판단 봇 7/1~10/20 KST 재현: A0 예전 재현(확인용), A1 지금 규칙(시간 정리 없음, 나스닥 22:00~23:00), "
                "A2 A1+시간 정리 4봉, A3 A1+바로 진입, A4 A1+판단 4/4, B1 A1+지정가 진입, B2 B1+계단 익절 지정가(낙관적 상한)",
       "notes": ["3.5개월·한 시장·거래 47~101번: 규칙 사이 차이는 운의 범위 안, 번다는 근거 아님",
                 "잰 것: 바이낸스 1분봉, 규칙봇 코드로 다시 계산한 신호, 저장소의 판단·검사 함수",
                 "가정: 미끄러짐 한쪽 0.02%, WOO X Pro 지정가 0.02%, 같은 1분봉 안 손절 먼저, 펀딩 없음, 발표 막기는 10월만",
                 "wallet: 7/1 00:00 KST $1,000, 창 안에서 진입한 거래만, 증거금 40% 복리",
                 "twin: 같은 진입·무작위 방향, 시드 1000+d, 200번; mean_roe_5_50_95 = 거래당 평균 순ROE의 분위"],
       "window_kst": ["2026-07-01", "2026-10-20"], "weekdays": NWD, "costs_per_side": COSTS, "variants": {}}
trades_of = {}
for tag in TAGS:
    T = pd.read_csv(f"{IN}/{tag}_trades.csv")
    S = json.load(open(f"{IN}/{tag}_summary.json"))
    W0_, W1_ = S["win"]
    T = T[(T.entry_time >= W0_) & (T.entry_time < W1_)].reset_index(drop=True)
    trades_of[tag] = T
    TW = pd.read_csv(f"{IN}/{tag}_twin.csv.gz")
    setup = json.load(open(f"{IN}/{tag}_setup.json"))
    v = {"setup": {k: setup[k] for k in ("entry", "lock_maker", "us_open_pause_min", "us_open_pre_min")}
         | {"time_bars": setup["trend"]["time_bars"], "vote_min": setup["trend"]["vote_min"]},
         "funnel": S["funnel"], "trades": int(len(T)),
         "entries_per_weekday": round(len(T) / NWD, 3),
         "weekend_entries": int(((T.entry_time + KST) // DAY + 3).mod(7).ge(5).sum()),
         "entry_kinds": T.entry_kind.value_counts().to_dict(), "by_cost": {}}
    # the paper cost set must give sim.py's own ROE
    r0, *_ = recost(T.side, T.lev, T.entry_ref.to_numpy(), T.entry_kind, T.exit_ref.to_numpy(), T.exit_kind,
                    COSTS["paper"])
    assert np.allclose(r0, T.roe.to_numpy(), atol=1e-9), float(np.abs(r0 - T.roe.to_numpy()).max())
    for cname, c in COSTS.items():
        roe, before, slip, fee = recost(T.side, T.lev, T.entry_ref.to_numpy(), T.entry_kind, T.exit_ref.to_numpy(),
                                        T.exit_kind, c)
        tw_roe, *_ = recost(TW.side, TW.lev, TW.entry_ref.to_numpy(), TW.entry_kind, TW.exit_ref.to_numpy(),
                            TW.exit_kind, c)
        draw_mean = pd.Series(tw_roe).groupby(TW.draw.to_numpy()).mean()
        draw_wallet = pd.Series(tw_roe).groupby(TW.draw.to_numpy()).apply(lambda x: W0 * np.prod(1 + MARGIN * x))
        rng = np.random.default_rng(7)
        boot = np.array([roe[rng.integers(0, len(roe), len(roe))].mean() for _ in range(4000)])
        first = T.entry_time.to_numpy() < HALF
        reasons = {}
        for k, g in pd.Series(roe).groupby(T.reason.to_numpy()):
            reasons[k] = {"n": int(len(g)), "mean_roe": round(float(g.mean()), 4)}
        v["by_cost"][cname] = {
            "win_rate": round(float((roe > 0).mean()), 3), "mean_roe": round(float(roe.mean()), 4),
            "median_roe": round(float(np.median(roe)), 4), "mean_roe_before_cost": round(float(before.mean()), 4),
            "win_rate_before_cost": round(float((before > 0).mean()), 3),
            "mean_cost_slippage": round(float(slip.mean()), 4), "mean_cost_fees": round(float(fee.mean()), 4),
            "mean_roe_90ci_bootstrap": [round(float(np.quantile(boot, q)), 4) for q in (0.05, 0.95)],
            "halves_mean_roe": [round(float(roe[first].mean()), 4), round(float(roe[~first].mean()), 4)],
            "halves_trades": [int(first.sum()), int((~first).sum())],
            "exits": dict(sorted(reasons.items(), key=lambda kv: -kv[1]["n"])),
            "wallet": wallet_stats(roe),
            "twin": {"draws": int(len(draw_mean)),
                     "mean_roe_5_50_95": [round(float(np.quantile(draw_mean, q)), 4) for q in (0.05, 0.5, 0.95)],
                     "wallet_end_5_50_95": [round(float(np.quantile(draw_wallet, q)), 1) for q in (0.05, 0.5, 0.95)],
                     "share_of_draws_with_mean_at_or_above_bot": round(float((draw_mean >= roe.mean()).mean()), 3)}}
    res["variants"][tag] = v


# B1 / B2 against A1: the same signals entered or not
def key(T):
    return set(zip(T.label, T.symbol, T.sig_t))


if "A1" in trades_of:
    a1 = trades_of["A1"]
    fa = pd.read_csv(f"{IN}/A1_fates.csv").set_index(["label", "symbol", "sig_t"]).fate
    for tag in [t for t in TAGS if t.startswith("B")]:
        b = trades_of[tag]
        fb = pd.read_csv(f"{IN}/{tag}_fates.csv").set_index(["label", "symbol", "sig_t"]).fate
        ka, kb = key(a1), key(b)
        lost, new, both = sorted(ka - kb), sorted(kb - ka), sorted(ka & kb)
        ia = a1.set_index(["label", "symbol", "sig_t"])
        ib = b.set_index(["label", "symbol", "sig_t"])
        out = {"A1_entries": len(ka), "entries": len(kb), "lost": len(lost), "new": len(new), "same_signal": len(both)}
        for cname, c in COSTS.items():
            def r(T):
                return pd.Series(recost(T.side, T.lev, T.entry_ref.to_numpy(), T.entry_kind, T.exit_ref.to_numpy(),
                                        T.exit_kind, c)[0], index=T.index)
            ra, rb = r(ia), r(ib)
            ba = pd.Series(recost(ia.side, ia.lev, ia.entry_ref.to_numpy(), ia.entry_kind, ia.exit_ref.to_numpy(),
                                  ia.exit_kind, c)[1], index=ia.index)
            bb = pd.Series(recost(ib.side, ib.lev, ib.entry_ref.to_numpy(), ib.entry_kind, ib.exit_ref.to_numpy(),
                                  ib.exit_kind, c)[1], index=ib.index)
            out[cname] = {
                "sum_roe_A1": round(float(ra.sum()), 3), "sum_roe": round(float(rb.sum()), 3),
                "lost_sum_roe_in_A1": round(float(ra.loc[lost].sum()), 3) if lost else 0.0,
                "new_sum_roe": round(float(rb.loc[new].sum()), 3) if new else 0.0,
                "same_signal_sum_roe_A1": round(float(ra.loc[both].sum()), 3),
                "same_signal_sum_roe": round(float(rb.loc[both].sum()), 3),
                "same_signal_mean_before_cost_A1": round(float(ba.loc[both].mean()), 4),
                "same_signal_mean_before_cost": round(float(bb.loc[both].mean()), 4)}
        out["lost_detail"] = [{"signal": f"{k[0]} {k[1]} {pd.to_datetime(k[2] + KST, unit='ms'):%m-%d %H:%M} KST",
                               "A1_reason": str(ia.loc[k].reason), "A1_roe": round(float(ia.loc[k].roe), 4),
                               "fate_here": str(fb.get(k, "?"))} for k in lost]
        out["new_detail"] = [{"signal": f"{k[0]} {k[1]} {pd.to_datetime(k[2] + KST, unit='ms'):%m-%d %H:%M} KST",
                              "reason": str(ib.loc[k].reason), "roe": round(float(ib.loc[k].roe), 4),
                              "fate_in_A1": str(fa.get(k, "?"))} for k in new]
        same_exit = int(sum(ia.loc[k].reason == ib.loc[k].reason for k in both))
        out["same_signal_same_exit_reason"] = same_exit
        A_, B_ = ia.loc[both], ib.loc[both]
        # > 0: A1's market reference price (the open after the touch) was better than this variant's limit price
        out["same_signal_mean_entry_gap_roe"] = round(float((A_.lev * A_.side * (B_.entry_ref - A_.entry_ref)
                                                             / A_.entry_ref).mean()), 4)
        out["same_signal_share_A1_price_better"] = round(float(((B_.entry_ref - A_.entry_ref) * A_.side > 0).mean()), 3)
        res["variants"][tag]["vs_A1"] = out

# parity: A0 against the 10-21 replay's trade list kept in the repo (data/trend_replay_0701_1020.json)
if "A0" in trades_of:
    from common import REPO
    ref = json.load(open(f"{REPO}/data/trend_replay_0701_1020.json"))
    old = pd.DataFrame(ref["trade_list"])
    a0 = trades_of["A0"]
    new = pd.DataFrame({"entry_time": a0.entry_time, "exit_time": a0.exit_time, "member": a0.label,
                        "symbol": a0.symbol, "side": np.where(a0.side > 0, "long", "short"), "reason": a0.reason,
                        "roe": a0.roe.round(4)})
    cols = ["entry_time", "exit_time", "member", "symbol", "side", "reason"]
    same = len(old) == len(new) and bool((old[cols].to_numpy() == new[cols].to_numpy()).all())
    res["parity_A0"] = {"reference": "data/trend_replay_0701_1020.json trade_list", "trades_reference": int(len(old)),
                        "trades_A0": int(len(new)), "same_entries_exits_reasons": same,
                        "max_abs_roe_diff": round(float(np.abs(old.roe.to_numpy() - new.roe.to_numpy()).max()), 6)
                        if len(old) == len(new) else None,
                        "reference_summary": {k: ref["trades"][k] for k in ("n", "win_rate", "roe_mean",
                                                                            "roe_mean_before_costs")}}
    print("parity A0:", res["parity_A0"])

# what the TIME exit did (A2 = A1 + TIME 4 bars): the same signals entered in both, the A2 trades closed by TIME and
# how the very same entries ended in A1 (no TIME exit)
if "A1" in trades_of and "A2" in trades_of:
    ia = trades_of["A1"].set_index(["label", "symbol", "sig_t"])
    ib = trades_of["A2"].set_index(["label", "symbol", "sig_t"])
    both = sorted(set(ia.index) & set(ib.index))
    tm = [k for k in both if ib.loc[k].reason == "TIME"]
    ra = ia.loc[tm]
    res["time_exit_A2_vs_A1"] = {
        "same_signal": len(both), "A2_time_exits_on_same_signal": len(tm),
        "their_A2_mean_roe": round(float(ib.loc[tm].roe.mean()), 4),
        "their_A1_mean_roe": round(float(ra.roe.mean()), 4),
        "their_A1_exits": {k: {"n": int(len(g)), "mean_roe": round(float(g.roe.mean()), 4)}
                           for k, g in ra.groupby("reason")},
        "their_A1_wins": int((ra.roe > 0).sum()),
        "A1_only": len(set(ia.index) - set(ib.index)), "A2_only": len(set(ib.index) - set(ia.index))}

os.makedirs(OUTDIR, exist_ok=True)
json.dump(res, open(f"{OUTDIR}/results.json", "w"), indent=1, ensure_ascii=False)


def pct(x, d=1):
    return f"{100 * x:+.{d}f}%"


for cname in COSTS:
    print(f"\n### cost set: {cname}\n")
    print("| 변형 | 진입 | 평일 하루 | 승률 | 순ROE 평균 | 순ROE 가운데 | 비용 전 평균 | 미끄러짐 | 수수료 | 지갑 끝 | 최악 낙폭 | 최장 연속 손실 | 동전 5–95% |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for tag in TAGS:
        v = res["variants"][tag]
        b = v["by_cost"][cname]
        tw = b["twin"]["mean_roe_5_50_95"]
        print(f"| {tag} | {v['trades']} | {v['entries_per_weekday']:.2f} | {100 * b['win_rate']:.0f}% | "
              f"{pct(b['mean_roe'])} | {pct(b['median_roe'])} | {pct(b['mean_roe_before_cost'])} | "
              f"{100 * b['mean_cost_slippage']:.1f}%p | {100 * b['mean_cost_fees']:.1f}%p | ${b['wallet']['end']:,.0f} | "
              f"{100 * b['wallet']['worst_drawdown']:.0f}% | {b['wallet']['longest_losing_run']} | "
              f"{pct(tw[0])} ~ {pct(tw[2])} |")
print("\n### exits (paper costs)\n")
for tag in TAGS:
    ex = res["variants"][tag]["by_cost"]["paper"]["exits"]
    print(tag, " · ".join(f"{k} {e['n']} ({pct(e['mean_roe'])})" for k, e in ex.items()))
print("\n### halves, bootstrap, twin share (paper costs)\n")
for tag in TAGS:
    b = res["variants"][tag]["by_cost"]["paper"]
    print(tag, "halves", [pct(x) for x in b["halves_mean_roe"]], b["halves_trades"], "ci90", [pct(x) for x in b["mean_roe_90ci_bootstrap"]],
          "twin>=bot", b["twin"]["share_of_draws_with_mean_at_or_above_bot"], "twin wallet", b["twin"]["wallet_end_5_50_95"],
          "wallet", b["wallet"])
print("TIME A2 vs A1", res.get("time_exit_A2_vs_A1"))
for tag in TAGS:
    if "vs_A1" in res["variants"][tag]:
        print(tag, "vs A1", res["variants"][tag]["vs_A1"])
