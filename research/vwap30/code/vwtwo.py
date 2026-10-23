"""참고 read (no selection): the two strategies the owners named on 10/23 from the DeepSeek ranking, VWAP fail 30m and EMA
fan 30m, at the rule bot's form (2 ATR + its ladder, margin 30 % x 30x = 9x exposure, every day, one position).
How common is the live 19-day result in 5 years, what usually came after, do they pick direction better than a coin,
how did round 8's judge x exit cells for them do on the confirm period, and the two together in one account.

    python3 -I vwtwo.py   -> research/vwap30/twostrat.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwstages3 import *
from vwgate import OUT8, GATES, LABELS
from vwconfirm import pick

TWO = {"F6_VWAP_FAIL_at_30m": ("VWAP 복귀 실패 30분", 0.678, 70), "F4_FAN_at_30m": ("EMA 부채 정렬 30분", 0.432, 47)}
LIVE0 = ms("2026-10-05T19:30")
ALL = (SEL[0], CONF[1])
SEED = 20261104


def all_mask(b):
    return np.ones(len(b.entry), bool)


def runs(b, live_ret, k):
    a, z = ALL
    idx, net, ext, D = trades(b, (b.entry >= a) & (b.entry < z), 0)
    x = 9.0 * net
    lg = np.log1p(np.maximum(x, -1 + 1e-12))
    win, loss = net[net > 0], net[net <= 0]
    d = (b.entry[idx] + KST) // DAY
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    per = np.zeros(d1 - d0 + 1)
    np.add.at(per, d - d0, lg)
    cs = np.r_[0, np.cumsum(per)]
    r19 = np.expm1(cs[19:] - cs[:-19])
    c = np.r_[0, np.cumsum(lg)]
    rk = np.expm1(c[k:] - c[:-k])
    i = np.arange(len(rk))
    ok = i + 2 * k <= len(lg)
    nxt = np.expm1(c[i[ok] + 2 * k] - c[i[ok] + k])
    good = rk[ok] >= live_ret
    return {"trades": int(len(idx)), "win": round(float((net > 0).mean()), 4),
            "avg_win_pct": round(float(win.mean() * 100), 3), "avg_loss_pct": round(float(loss.mean() * 100), 3),
            "avg_net_pct": round(float(net.mean() * 100), 4),
            "breakeven_win": round(float(-loss.mean() / (win.mean() - loss.mean())), 4),
            "d19_share_ge_live": round(float((r19 >= live_ret).mean()), 4), "d19_median": round(float(np.median(r19)), 3),
            "d19_share_pos": round(float((r19 > 0).mean()), 4),
            "run_share_ge_live": round(float((rk >= live_ret).mean()), 4),
            "after_good_run_next_pos": round(float((nxt[good] > 0).mean()), 4) if good.any() else None,
            "after_good_run_next_median": round(float(np.median(nxt[good])), 3) if good.any() else None,
            "good_runs": int(good.sum())}


def live(b):
    idx, net, ext, D = trades(b, b.entry >= LIVE0, 0)
    return {"n": int(len(idx)), "win": int((net > 0).sum()), "mult_9x": round(float(np.prod(1 + np.maximum(9 * net, -1))), 3)}


def twin(b, per):
    rng = np.random.default_rng(SEED)
    m = all_mask(b)
    g = metrics(b, m, 0, per, full=False)["growth"]
    tw = np.array([metrics(b, m, 0, per, flip=rng.random(len(b.entry)) < 0.5, full=False)["growth"] for _ in range(1000)])
    return {"growth": round(g, 3), "twin_p50": round(float(np.median(tw)), 3), "share_below": round(float((tw < g).mean()), 3)}


def round8_after(lab):
    """Round 8's whole judge x exit grid for this trigger on the confirm period (read after the round 8 verdicts)."""
    S = np.load(os.path.join(OUT8, "scan", f"{lab}.npz"))["out"].astype(float)
    C = np.load(os.path.join(OUT8, "cscan", f"{lab}.npz"))["out"].astype(float)
    keep = np.array([not (g.startswith("L|") and g.split("|")[1] == lab) for g in GATES] + [True])
    S, C = S[keep].reshape(-1, 6), C[keep].reshape(-1, 6)
    nS, nC = S[:, 0] + S[:, 1], C[:, 0] + C[:, 1]
    with np.errstate(all="ignore"):
        rS, rC = (S[:, 2] + S[:, 3]) / nS, (C[:, 2] + C[:, 3]) / nC
    m = (nS >= 300) & (nC >= 50)
    wd_c = 0
    both = m & (S[:, 2] > 0) & (S[:, 3] > 0)
    return {"cells": int(m.sum()), "confirm_R_pos_share": round(float(np.mean(rC[m] > 0)), 4),
            "confirm_R_mean": round(float(np.nanmean(rC[m])), 4),
            "select_both_halves_pos": int(both.sum()),
            "of_those_confirm_pos_share": round(float(np.mean(rC[both] > 0)), 4) if both.any() else None}


def main():
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    out = {}
    ones = []
    for lab, (ko, live_ret, k) in TWO.items():
        b = Label(lab).one(EX_HOUSE2)
        ones.append(b)
        row = {"ko": ko, "live_ret": live_ret, "five_year": runs(b, live_ret, k), "live_sim": live(b),
               "select_rb9": pick(metrics(b, all_mask(b), 0, "select", r="rb9")),
               "confirm_rb9": pick(metrics(b, all_mask(b), 0, "confirm", r="rb9")),
               "twin_select": twin(b, "select"), "twin_confirm": twin(b, "confirm"),
               "round8_after": round8_after(lab)}
        out[lab] = row
        print(ko, json.dumps(row, ensure_ascii=False), flush=True)
    both = merge([Label(lab).one(EX_HOUSE2, prio=i) for i, lab in enumerate(TWO)])
    out["both"] = {per: pick(metrics(both, all_mask(both), 0, per, r="rb9")) for per in ("select", "confirm", "c2025", "c2026", "live")}
    out["both_weekday"] = {per: pick(metrics(both, wd_mask(both), 0, per, r="rb9")) for per in ("select", "confirm", "live")}
    out["both_runs"] = runs(both, 0.5, 100)
    print("both", json.dumps(out["both"], ensure_ascii=False))
    print("both weekday", json.dumps(out["both_weekday"], ensure_ascii=False))
    json.dump(out, open(os.path.join(RES_DIR, "twostrat.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
