"""candleague/summary.py kinds / pairs / events (the owner-exit league's league.json keys) and the dashboard's /api/judge, on hand-made
accounts and trades (no network): the kinds' numbers on a tiny example computed by hand, the DeepSeek money rule both ways (D11: with
``ds_money`` off nothing of a DeepSeek account's ROE, money or return reaches any of the three keys, whatever the rows and the book hold),
the pairs' matching (unmatched trades on both sides, the control account only, the 'same' band), the events (switch, narrowed, rule exit,
the newest 200), an empty book, determinism, and write_snapshots carrying the keys in the owner-exit league and only there."""

from __future__ import annotations

import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from candleague import candidates as C  # noqa: E402
from candleague import dash as D  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import summary as SM  # noqa: E402
from candleague.live import Live  # noqa: E402

H, DAY, MIN = 3_600_000, 86_400_000, 60_000
T0 = 1_791_000_000_000                       # a minute boundary
E0 = 1000.0                                  # the start wallet of these tests (passed as equity0)
P1, P2 = "core-DOGE-15m-1", "ds-F5_BOX-1h-1"

LINEUP = [
    {"role": "fq", "suffix": "-fq", "label_ko": "메인 · 구조 확실히 무너지면 빠른 손절", "short_ko": "빠른 손절"},
    {"role": "nv", "suffix": "-nv", "label_ko": "메인 · 매매법 자체 판단으로 청산", "short_ko": "자체 판단"},
    {"role": "sw", "suffix": "-sw", "label_ko": "메인 · 반대 신호 나오면 스위칭", "short_ko": "스위칭"},
    {"role": "tg", "suffix": "-tg", "label_ko": "메인 · 구조 무너지면 손절 좁힘", "short_ko": "손절 좁힘"},
    {"role": "ld", "suffix": "-ld", "label_ko": "대조 · 계단 · 손절 최대 2 ATR (원래 메인)", "short_ko": "계단"},
    {"role": "ldc", "suffix": "-ldc", "label_ko": "대조 · 계단 · 동전 던지기", "short_ko": "동전"},
    {"role": "gb", "suffix": "-gb", "label_ko": "큰 수익 반납 보호", "short_ko": "수익 보호"},
]


def acct(pick, role, kind=None, name=None, tf=None):
    kind = kind or pick.split("-")[0]
    return {"id": f"{pick}-{role}", "pick": pick, "role": role, "kind": kind,
            "name": name or ("DOGE" if kind == "core" else "F5_BOX"), "tf": tf or ("15m" if kind == "core" else "1h")}


def trade(sym, side, entry_h, exit_h, reason, roe, margin=100.0, entry_extra=0):
    """A closed trade; pnl = roe x margin (so the wallet moves by hand-checkable amounts)."""
    return {"symbol": sym, "side": side, "entry_time": T0 + int(entry_h * H) + entry_extra, "exit_time": T0 + int(exit_h * H),
            "exit_reason": reason, "roe": roe, "pnl": roe * margin}


def wallet(trades):
    return E0 + sum(t["pnl"] for t in trades)


def rows_of(book, accts, open_ids=(), ds_leak=True):
    """account_rows-like rows: wallet, closed-trade drawdown and the open position (a DeepSeek row's money None unless ds_leak)."""
    out = []
    for a in accts:
        eq = peak = E0
        dd = 0.0
        for t in book.get(a["id"], []):
            eq += t["pnl"]
            peak = max(peak, eq)
            dd = max(dd, 1 - eq / peak)
        row = {"id": a["id"], "wallet": eq, "max_dd": dd, "open": {"symbol": "DOGEUSDT", "side": 1, "since": T0} if a["id"] in open_ids else None}
        if a["kind"] == "ds" and not ds_leak:
            row["wallet"] = row["max_dd"] = None
        out.append(row)
    return out


# ---------------------------------------------------------------- kinds
def kinds_example():
    accts = [acct(P1, "fq"), acct(P2, "fq"), acct(P1, "ld"), acct(P2, "ld")]
    t2 = trade("DOGEUSDT", -1, 3, 7, "RULE", 0.30)
    u1 = trade("BTCUSDT", 1, 1, 4, "LOCK", 0.50)
    book = {
        P1 + "-fq": [trade("DOGEUSDT", 1, 0, 2, "SL", -0.10), t2, trade("DOGEUSDT", 1, 8, 9, "RULE", 0.10),
                     trade("DOGEUSDT", 1, 10, 16, "TP", 0.20), trade("DOGEUSDT", -1, 17, 18, "LIQ", -1.0)],
        P2 + "-fq": [u1, trade("BTCUSDT", 1, 5, 6, "SL", -0.20)],
        P1 + "-ld": [trade("DOGEUSDT", 1, 0, 2, "SL", -0.10)],
        P2 + "-ld": [],
    }
    narrowed = {(P1 + "-fq", t2["entry_time"], t2["exit_time"]), (P2 + "-fq", u1["entry_time"], u1["exit_time"])}
    return accts, book, narrowed


def kinds_of(ds_money, accts=None, book=None, narrowed=None, open_ids=(P1 + "-fq", P2 + "-fq"), end=T0 + 2 * DAY):
    ex_accts, ex_book, ex_narrowed = kinds_example()
    accts, book = accts or ex_accts, book or ex_book
    rows = rows_of(book, accts, open_ids)
    return SM.kinds_summary(LINEUP, accts, book, rows, T0, end, ds_money, ex_narrowed if narrowed is None else narrowed, E0)


def test_kinds_by_hand_with_deepseek_money_hidden():
    ks = kinds_of(False)
    assert [k["role"] for k in ks] == [x["role"] for x in LINEUP]                       # the lineup's order, one dict per kind
    assert [k["group"] for k in ks] == ["main", "main", "main", "main", "control", "control", "research"]
    fq = ks[0]
    assert (fq["suffix"], fq["label_ko"], fq["short_ko"], fq["accounts"], fq["picks"]) == ("-fq", LINEUP[0]["label_ko"], "빠른 손절", 2, 2)
    # counts: both accounts, DeepSeek too (7 trades; the wins are P&L > 0: three core, one DeepSeek)
    assert (fq["trades"], fq["wins"]) == (7, 4) and fq["win_rate"] == pytest.approx(4 / 7)
    assert fq["reasons"] == {"SL": 2, "LOCK": 1, "RULE": 2, "TP": 1, "LIQ": 1}
    assert fq["median_hold_h"] == 2.0                                                   # holds 2 4 1 6 1 | 3 1 hours -> 1 1 1 2 3 4 6
    assert fq["trades_per_day"] == pytest.approx(3.5) and fq["narrowed_n"] == 2 and fq["open_now"] == 2
    # ROE and money: the core account only (-0.10, +0.30, +0.10, +0.20, -1.00)
    assert fq["avg_win_roe"] == pytest.approx(0.2) and fq["avg_loss_roe"] == pytest.approx(-0.55)
    assert fq["payoff"] == pytest.approx(0.2 / 0.55) and fq["mean_roe"] == pytest.approx(-0.1)
    assert fq["reason_mean_roe"] == {"SL": pytest.approx(-0.1), "LOCK": None, "RULE": pytest.approx(0.2), "TP": pytest.approx(0.2),
                                     "LIQ": pytest.approx(-1.0)}
    assert fq["wallet_return_pct"] == pytest.approx(-0.05)                              # 950 / 1000 - 1
    assert fq["max_dd_mean"] == pytest.approx(100 / 1050)                               # 1050 -> 950
    assert (fq["best_pick"], fq["worst_pick"]) == (P1, P1) and fq["best_pick_roe"] == pytest.approx(-0.1)   # the DeepSeek pick has 2 trades anyway
    assert fq["ds_in_roe"] is False
    # a control kind with one core trade and a DeepSeek account without any
    ld = ks[4]
    assert (ld["accounts"], ld["picks"], ld["trades"], ld["wins"], ld["open_now"]) == (2, 1, 1, 0, 0)
    assert ld["win_rate"] == 0.0 and ld["avg_win_roe"] is None and ld["avg_loss_roe"] == pytest.approx(-0.1) and ld["payoff"] is None
    assert ld["trades_per_day"] == pytest.approx(0.5) and ld["wallet_return_pct"] == pytest.approx(-0.01)
    assert ld["best_pick"] is None                                                      # 1 trade < 5
    # a kind without accounts
    nv = ks[1]
    assert (nv["accounts"], nv["picks"], nv["trades"], nv["wins"], nv["win_rate"], nv["mean_roe"], nv["median_hold_h"]) == (0, 0, 0, 0, None, None, None)
    assert nv["reasons"] == dict.fromkeys(SM.REASONS, 0) and nv["reason_mean_roe"] == dict.fromkeys(SM.REASONS) and nv["wallet_return_pct"] is None
    assert nv["max_dd_mean"] is None and nv["payoff"] is None and nv["trades_per_day"] == 0.0 and nv["worst_pick"] is None


def test_kinds_with_deepseek_money_shown():
    ks = kinds_of(True)
    fq = ks[0]
    assert fq["ds_in_roe"] is True and (fq["trades"], fq["wins"]) == (7, 4)             # the counts do not change
    assert fq["avg_win_roe"] == pytest.approx((0.3 + 0.1 + 0.2 + 0.5) / 4)
    assert fq["avg_loss_roe"] == pytest.approx((-0.1 - 1.0 - 0.2) / 3)
    assert fq["payoff"] == pytest.approx(0.275 / (1.3 / 3))
    assert fq["mean_roe"] == pytest.approx(-0.2 / 7)
    assert fq["reason_mean_roe"]["SL"] == pytest.approx(-0.15) and fq["reason_mean_roe"]["LOCK"] == pytest.approx(0.5)
    assert fq["wallet_return_pct"] == pytest.approx((-0.05 + 0.03) / 2)                 # 950 and 1030
    assert fq["max_dd_mean"] == pytest.approx((100 / 1050 + 20 / 1050) / 2)
    assert (fq["best_pick"], fq["worst_pick"]) == (P1, P1)                              # 5 trades: the DeepSeek pick has 2
    ld = ks[4]
    assert ld["wallet_return_pct"] == pytest.approx((-0.01 + 0.0) / 2) and ld["ds_in_roe"] is True


def test_kinds_deepseek_never_reaches_a_money_field_when_hidden():
    """Change every DeepSeek ROE / P&L (keeping the win or loss) and the DeepSeek wallets: with the switch off nothing may change; with
    it on the ROE figures must change (so the test could fail)."""
    accts, book, narrowed = kinds_example()
    book2 = copy.deepcopy(book)
    for t in book2[P2 + "-fq"]:
        t["roe"], t["pnl"] = t["roe"] * 7, t["pnl"] * 7
    rows = rows_of(book, accts, (P1 + "-fq",))
    rows2 = rows_of(book2, accts, (P1 + "-fq",))
    rows2[1]["wallet"], rows2[1]["max_dd"] = 99999.0, 0.9
    off = SM.kinds_summary(LINEUP, accts, book, rows, T0, T0 + 2 * DAY, False, narrowed, E0)
    assert SM.kinds_summary(LINEUP, accts, book2, rows2, T0, T0 + 2 * DAY, False, narrowed, E0) == off
    on = SM.kinds_summary(LINEUP, accts, book, rows, T0, T0 + 2 * DAY, True, narrowed, E0)
    assert SM.kinds_summary(LINEUP, accts, book2, rows2, T0, T0 + 2 * DAY, True, narrowed, E0) != on
    # hidden rows as the engine writes them (wallet and drawdown None) give the same figures as leaking ones
    hidden = rows_of(book, accts, (P1 + "-fq",), ds_leak=False)
    assert SM.kinds_summary(LINEUP, accts, book, hidden, T0, T0 + 2 * DAY, False, narrowed, E0) == off
    # a kind that holds DeepSeek accounts only has no money figure at all while hidden
    only = [acct(P2, "fq"), acct(P2, "ld")]
    k = SM.kinds_summary(LINEUP, only, {P2 + "-fq": book[P2 + "-fq"], P2 + "-ld": []}, rows_of(book, only), T0, T0 + 2 * DAY, False, narrowed, E0)[0]
    assert (k["trades"], k["wins"], k["reasons"]["LOCK"]) == (2, 1, 1)
    assert all(k[f] is None for f in ("avg_win_roe", "avg_loss_roe", "payoff", "mean_roe", "wallet_return_pct", "max_dd_mean", "best_pick",
                                       "worst_pick", "best_pick_roe", "worst_pick_roe"))
    assert set(k["reason_mean_roe"].values()) == {None}


def test_kinds_trades_per_day_waits_for_a_day_and_best_worst_need_five_trades():
    assert kinds_of(False, end=T0 + DAY - 1)[0]["trades_per_day"] is None
    assert kinds_of(False, end=T0 + DAY)[0]["trades_per_day"] == pytest.approx(7.0)
    assert SM.kinds_summary(LINEUP, [], {}, [], None, None)[0]["trades_per_day"] is None
    # six picks of one kind: the best and the worst by mean ROE among those with 5+ trades (a 4-trade pick is never named)
    accts, book = [], {}
    means = {"a": 0.10, "b": -0.30, "c": 0.02, "d": 0.50, "e": -0.05}
    for i, (x, m) in enumerate(means.items()):
        p = f"core-DOGE-15m-{i + 1}"
        accts.append(acct(p, "nv"))
        n = 4 if x == "d" else 5                                                           # the best mean has too few trades
        book[p + "-nv"] = [trade("DOGEUSDT", 1, 3 * j, 3 * j + 1, "SL", m) for j in range(n)]
    k = SM.kinds_summary(LINEUP, accts, book, rows_of(book, accts), T0, T0 + 3 * DAY, False, None, E0)[1]
    assert (k["best_pick"], k["worst_pick"]) == ("core-DOGE-15m-1", "core-DOGE-15m-2") and k["picks"] == 5
    assert (k["best_pick_roe"], k["worst_pick_roe"]) == (pytest.approx(0.10), pytest.approx(-0.30))


def test_kind_groups_on_the_real_lineup():
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, RX.normalize_owner(doc))
    lu = RX.lineup(accts)
    ks = SM.kinds_summary(lu, accts, {}, [], None, None)
    by = {g: [k["suffix"] for k in ks if k["group"] == g] for g in ("main", "control", "research")}
    # the group follows the file's labels (메인 / 대조 / anything else), in the file's order
    for g, word in (("main", "메인"), ("control", "대조")):
        assert by[g] == [e["suffix"] for e in doc["owner_exits"] if e["label_ko"].startswith(word)]
    assert by["main"][:4] == ["-fq", "-nv", "-sw", "-tg"] and by["control"] == ["-ld", "-ldc", "-fqc", "-ldp", "-ld1"]
    assert len(by["research"]) == len(lu) - len(by["main"]) - len(by["control"]) > 0
    assert [k["role"] for k in ks] == [x["role"] for x in lu]
    assert [k["accounts"] for k in ks] == [x["accounts"] for x in lu] and sum(k["accounts"] for k in ks) == len(accts)
    assert SM.kind_group("  메인 · x") == "main" and SM.kind_group("지금 청산") == "research" and SM.kind_group(None) == "research"


# ---------------------------------------------------------------- pairs
def pairs_example():
    Pc, Pd = "core-DOGE-15m-1", "ds-F5_BOX-1h-1"
    accts = [acct(Pc, "fq"), acct(Pc, "sw"), acct(Pc, "ld"), acct(Pc, "ldc"), acct(Pc, "gb"),
             acct(Pd, "fq"), acct(Pd, "nv"), acct(Pd, "ld")]
    book = {
        Pc + "-ld": [trade("BTCUSDT", 1, 1, 2, "SL", -0.10), trade("BTCUSDT", -1, 5, 6, "TP", 0.20),
                     trade("ETHUSDT", 1, 9, 10, "TP", 0.05), trade("ETHUSDT", 1, 13, 14, "TP", 0.10)],
        Pc + "-fq": [trade("BTCUSDT", 1, 1, 3, "RULE", 0.10),                              # vs ld: +0.20 better
                     trade("BTCUSDT", -1, 5, 7, "SL", 0.2004),                             # +0.0004: inside the band, same
                     trade("ETHUSDT", -1, 9, 11, "SL", -0.02),                             # the control went long: no pair
                     trade("ETHUSDT", 1, 13, 15, "SL", -0.05),                             # -0.15 worse
                     trade("SOLUSDT", 1, 30, 31, "TP", 0.10)],                             # the control took no SOL: no pair
        Pc + "-sw": [trade("BTCUSDT", 1, 1, 2, "SL", -0.10),                               # equal: same
                     trade("ETHUSDT", 1, 9, 12, "RULE", 0.0545)],                          # +0.0045 better
        Pc + "-ldc": [trade("BTCUSDT", 1, 1, 2, "SL", 0.90)],                              # not the control
        Pc + "-gb": [trade("ETHUSDT", 1, 13, 14, "SL", 0.90)],                             # a research kind: no pair
        Pd + "-ld": [trade("SOLUSDT", 1, 2, 4, "SL", -0.10), trade("SOLUSDT", 1, 20, 22, "TP", 0.10)],
        Pd + "-fq": [trade("SOLUSDT", 1, 2, 3, "TP", 0.30), trade("SOLUSDT", 1, 20, 21, "SL", -0.20)],
        Pd + "-nv": [trade("SOLUSDT", 1, 2, 5, "RULE", 0.05)],
    }
    return accts, book


def pairs_of(ds_money):
    accts, book = pairs_example()
    return SM.pairs_summary(LINEUP, accts, book, ds_money, E0)


def test_pairs_matching_and_the_core_numbers_by_hand():
    pr = pairs_of(False)
    assert pr["control"] == "-ld" and list(pr["by_role"]) == ["fq", "nv", "sw", "tg"]       # the main kinds, lineup order
    fq, nv, sw, tg = (pr["by_role"][r] for r in ("fq", "nv", "sw", "tg"))
    # fq: three core pairs (better / same / worse; two trades have no control twin) + two DeepSeek pairs counted in n only
    assert (fq["n"], fq["n_shown"], fq["better"], fq["worse"], fq["same"]) == (5, 3, 1, 1, 1)
    assert fq["mean_diff_roe"] == pytest.approx((0.20 + 0.0004 - 0.15) / 3) and fq["pct_better"] == pytest.approx(1 / 3)
    # the wallet share: each side's P&L over its own wallet before the trade (fq 1000 / 1010 / 1030.04 / 1028.04, ld 1000 / 990 / 1010 / 1015)
    assert fq["sum_diff_pct_of_wallet"] == pytest.approx(0.02 + (20.04 / 1010 - 20 / 990) + (-5 / 1028.04 - 10 / 1015))
    assert (sw["n"], sw["n_shown"], sw["better"], sw["worse"], sw["same"]) == (2, 2, 1, 0, 1)
    assert sw["mean_diff_roe"] == pytest.approx(0.0045 / 2) and sw["pct_better"] == 0.5
    assert sw["sum_diff_pct_of_wallet"] == pytest.approx(0.0 + (5.45 / 990 - 5 / 1010))
    # a role whose only pair is a hidden DeepSeek one: counted, nothing else
    assert nv == {"n": 1, "n_shown": 0, "better": None, "worse": None, "same": None, "mean_diff_roe": None,
                  "sum_diff_pct_of_wallet": None, "pct_better": None}
    assert tg == {"n": 0, "n_shown": 0, "better": None, "worse": None, "same": None, "mean_diff_roe": None,
                  "sum_diff_pct_of_wallet": None, "pct_better": None}
    # the newest pair first (ties: the later account id first); the control's twin and research kinds are never a side
    keys = [(p["pick"], p["role"], p["exit_time"]) for p in pr["recent"]]
    P_c, P_d = "core-DOGE-15m-1", "ds-F5_BOX-1h-1"
    assert keys == [(P_d, "fq", T0 + 21 * H), (P_c, "fq", T0 + 15 * H), (P_c, "sw", T0 + 12 * H), (P_c, "fq", T0 + 7 * H),
                    (P_d, "nv", T0 + 5 * H), (P_d, "fq", T0 + 3 * H), (P_c, "fq", T0 + 3 * H), (P_c, "sw", T0 + 2 * H)]
    f4 = pr["recent"][1]
    assert f4 == {"pick": P_c, "name": "DOGE", "tf": "15m", "kind": "core", "symbol": "ETHUSDT", "side": 1, "entry_time": T0 + 13 * H,
                  "exit_time": T0 + 15 * H, "role": "fq", "a_reason": "SL", "a_roe": -0.05, "b_reason": "TP", "b_roe": 0.10,
                  "diff_roe": pytest.approx(-0.15)}
    # DeepSeek pairs in the list: the reasons stay, every ROE is None
    d2 = pr["recent"][0]
    assert (d2["kind"], d2["a_reason"], d2["b_reason"]) == ("ds", "SL", "TP")
    assert d2["a_roe"] is None and d2["b_roe"] is None and d2["diff_roe"] is None
    assert all(p["a_roe"] is None and p["diff_roe"] is None for p in pr["recent"] if p["kind"] == "ds")


def test_pairs_with_deepseek_money_shown():
    pr = pairs_of(True)
    fq, nv = pr["by_role"]["fq"], pr["by_role"]["nv"]
    # + D1 (0.30 vs -0.10: better) and D2 (-0.20 vs 0.10: worse)
    assert (fq["n"], fq["n_shown"], fq["better"], fq["worse"], fq["same"]) == (5, 5, 2, 2, 1)
    assert fq["mean_diff_roe"] == pytest.approx((0.20 + 0.0004 - 0.15 + 0.40 - 0.30) / 5) and fq["pct_better"] == pytest.approx(0.4)
    assert fq["sum_diff_pct_of_wallet"] == pytest.approx(0.02 + (20.04 / 1010 - 20 / 990) + (-5 / 1028.04 - 10 / 1015)
                                                         + 0.04 + (-20 / 1030 - 10 / 990))
    assert (nv["n"], nv["n_shown"], nv["better"], nv["worse"], nv["same"], nv["pct_better"]) == (1, 1, 1, 0, 0, 1.0)
    assert nv["sum_diff_pct_of_wallet"] == pytest.approx(0.015)                              # 5 / 1000 - (-10 / 1000)
    d2 = pr["recent"][0]
    assert d2["a_roe"] == -0.20 and d2["b_roe"] == 0.10 and d2["diff_roe"] == pytest.approx(-0.30)


def test_pairs_the_same_band_edges_and_no_control_account():
    accts = [acct(P1, "fq"), acct(P1, "ld")]
    mk = lambda roe: {P1 + "-ld": [trade("BTCUSDT", 1, 1, 2, "SL", 0.0)], P1 + "-fq": [trade("BTCUSDT", 1, 1, 2, "SL", roe)]}   # noqa: E731
    got = {}
    for roe in (0.0005, 0.00049, -0.00049, -0.0005, 0.0):
        r = SM.pairs_summary(LINEUP, accts, mk(roe), False, E0)["by_role"]["fq"]
        got[roe] = (r["better"], r["worse"], r["same"])
    assert got == {0.0005: (1, 0, 0), 0.00049: (0, 0, 1), -0.00049: (0, 0, 1), -0.0005: (0, 1, 0), 0.0: (0, 0, 1)}
    # a pick without a control account has no pair; neither has a control trade with another entry time
    r = SM.pairs_summary(LINEUP, [acct(P1, "fq")], mk(0.1), False, E0)
    assert r["by_role"]["fq"]["n"] == 0 and r["recent"] == []
    off = mk(0.1)
    off[P1 + "-ld"][0]["entry_time"] += 1
    assert SM.pairs_summary(LINEUP, accts, off, False, E0)["by_role"]["fq"]["n"] == 0


def test_pairs_recent_keeps_the_newest_sixty():
    accts = [acct(P1, "fq"), acct(P1, "ld")]
    book = {P1 + "-ld": [trade("BTCUSDT", 1, 2 * i, 2 * i + 1, "SL", -0.1) for i in range(100)],
            P1 + "-fq": [trade("BTCUSDT", 1, 2 * i, 2 * i + 1, "TP", 0.1) for i in range(100)]}
    pr = SM.pairs_summary(LINEUP, accts, book, False, E0)
    assert pr["by_role"]["fq"]["n"] == 100 and len(pr["recent"]) == SM.PAIRS_RECENT == 60
    times = [p["exit_time"] for p in pr["recent"]]
    assert times == sorted(times, reverse=True) and times[0] == T0 + 199 * H and times[-1] == T0 + (2 * 40 + 1) * H


# ---------------------------------------------------------------- events
def events_example():
    Pc, Pd, Pe, Pf = "core-DOGE-15m-1", "ds-F5_BOX-1h-1", "core-ETH-1h-1", "core-LTC-1h-1"
    accts = [acct(Pc, "sw"), acct(Pc, "fq"), acct(Pc, "tg"), acct(Pc, "ld"), acct(Pd, "sw"), acct(Pe, "sw"), acct(Pf, "sw")]
    book = {
        Pc + "-sw": [trade("BTCUSDT", 1, 0, 2, "SL", -0.10),                                       # the next trade starts 20 s into the minute it ended
                     trade("BTCUSDT", -1, 2, 5, "RULE", 0.20, entry_extra=20_000),             # opposite side, same minute: W1 is a switch
                     trade("BTCUSDT", 1, 5, 8, "TP", 0.30, entry_extra=MIN),                   # a minute later: W2 stays a rule exit
                     trade("BTCUSDT", 1, 8, 9, "SL", -0.10)],                                  # same side: no switch (and not a rule exit)
        Pc + "-fq": [trade("BTCUSDT", 1, 0, 1, "RULE", 0.10), trade("BTCUSDT", 1, 3, 4, "SL", -0.20)],
        Pc + "-tg": [trade("ETHUSDT", 1, 1, 3, "SL", -0.10), trade("ETHUSDT", 1, 4, 6, "RULE", 0.05)],
        Pc + "-ld": [trade("BTCUSDT", 1, 0, 2, "RULE", -0.05)],                                    # the control: never an event of its own
        Pd + "-sw": [trade("SOLUSDT", 1, 0, 1, "RULE", 0.50)],
        Pe + "-sw": [trade("BTCUSDT", -1, 0, 3, "RULE", 0.10)],                                    # its reversal is still open (rows)
        Pf + "-sw": [trade("BTCUSDT", 1, 0, 4, "RULE", 0.10)],                                     # an open position on the same side: no switch
    }
    narrowed = {(Pc + "-tg", T0 + 1 * H, T0 + 3 * H), (Pc + "-tg", T0 + 4 * H, T0 + 6 * H)}
    rows = [{"id": Pe + "-sw", "open": {"symbol": "BTCUSDT", "side": 1, "since": T0 + 3 * H + 30_000}},
            {"id": Pf + "-sw", "open": {"symbol": "BTCUSDT", "side": 1, "since": T0 + 4 * H}}]
    return accts, book, narrowed, rows


def test_events_switch_narrowed_and_rule_exit():
    accts, book, narrowed, rows = events_example()
    ev = SM.events_summary(LINEUP, accts, book, narrowed, rows, False)
    got = [(e["account"], e["event"], e["time"]) for e in ev]
    # newest first; equal times: the later account id first. tg's second trade is narrowed AND a rule exit: narrowed wins
    assert got == [("core-DOGE-15m-1-tg", "narrowed", T0 + 6 * H), ("core-DOGE-15m-1-sw", "rule_exit", T0 + 5 * H),
                   ("core-LTC-1h-1-sw", "rule_exit", T0 + 4 * H), ("core-ETH-1h-1-sw", "switch", T0 + 3 * H),
                   ("core-DOGE-15m-1-tg", "narrowed", T0 + 3 * H), ("core-DOGE-15m-1-sw", "switch", T0 + 2 * H),
                   ("ds-F5_BOX-1h-1-sw", "rule_exit", T0 + 1 * H), ("core-DOGE-15m-1-fq", "rule_exit", T0 + 1 * H)]
    by = {(e["account"], e["time"]): e for e in ev}
    fq = by[("core-DOGE-15m-1-fq", T0 + H)]
    assert fq == {"time": T0 + H, "account": "core-DOGE-15m-1-fq", "pick": "core-DOGE-15m-1", "role": "fq", "name": "DOGE", "tf": "15m",
                  "kind": "core", "side": 1, "symbol": "BTCUSDT", "event": "rule_exit", "roe": 0.10, "hold_h": 1.0, "control_roe": -0.05}
    sw = by[("core-DOGE-15m-1-sw", T0 + 2 * H)]
    assert (sw["event"], sw["roe"], sw["hold_h"], sw["side"]) == ("switch", -0.10, 2.0, 1)
    assert by[("core-DOGE-15m-1-sw", T0 + 5 * H)]["hold_h"] == round(3 - 20 / 3600, 3) == 2.994        # hours, 3 decimals
    assert sw["control_roe"] == -0.05                                                       # the control's BTC long at T0 is the same decision
    assert by[("core-DOGE-15m-1-tg", T0 + 3 * H)]["control_roe"] is None                    # the control never traded ETH


def test_events_control_roe_and_deepseek_gating():
    accts, book, narrowed, rows = events_example()
    book["ds-F5_BOX-1h-1-ld"] = [trade("SOLUSDT", 1, 0, 2, "SL", -0.30)]                   # the DeepSeek control took the DeepSeek switch account's trade
    accts.append(acct("ds-F5_BOX-1h-1", "ld"))
    off = {(e["account"], e["time"]): e for e in SM.events_summary(LINEUP, accts, book, narrowed, rows, False)}
    on = {(e["account"], e["time"]): e for e in SM.events_summary(LINEUP, accts, book, narrowed, rows, True)}
    assert off[("core-DOGE-15m-1-fq", T0 + H)]["control_roe"] == -0.05 == on[("core-DOGE-15m-1-fq", T0 + H)]["control_roe"]
    d_off, d_on = off[("ds-F5_BOX-1h-1-sw", T0 + H)], on[("ds-F5_BOX-1h-1-sw", T0 + H)]
    assert (d_off["roe"], d_off["control_roe"]) == (None, None) and (d_off["hold_h"], d_off["kind"], d_off["event"]) == (1.0, "ds", "rule_exit")
    assert (d_on["roe"], d_on["control_roe"]) == (0.50, -0.30)
    assert {k for k, e in off.items() if e["kind"] == "core"} == {k for k, e in on.items() if e["kind"] == "core"}
    assert all(off[k] == on[k] for k in off if off[k]["kind"] == "core")                  # core rows do not depend on the switch
    assert not any(a.endswith("-ld") for a, _t in off)                                      # the control's own trades are never events


def test_events_keep_the_newest_two_hundred():
    accts = [acct(P1, "fq")]
    book = {P1 + "-fq": [trade("BTCUSDT", 1, 2 * i, 2 * i + 1, "RULE", 0.1) for i in range(250)] + [trade("BTCUSDT", 1, 600, 601, "SL", 0.1)]}
    ev = SM.events_summary(LINEUP, accts, book, None, None, False)
    assert len(ev) == SM.EVENTS_MAX == 200
    assert [e["time"] for e in ev] == [T0 + (2 * i + 1) * H for i in range(249, 49, -1)]


# ---------------------------------------------------------------- empty book, determinism
def test_empty_book():
    accts, _book = pairs_example()
    v = SM.owner_views(LINEUP, accts, {}, rows_of({}, accts), T0, T0 + 3 * DAY, False, set(), E0)
    assert set(v) == {"kinds", "pairs", "events"} and v["events"] == [] and v["pairs"]["recent"] == []
    assert all(r["n"] == 0 and r["better"] is None for r in v["pairs"]["by_role"].values())
    assert [k["trades"] for k in v["kinds"]] == [0] * len(LINEUP)
    assert v["kinds"][0]["wallet_return_pct"] == 0.0 and v["kinds"][0]["max_dd_mean"] == 0.0 and v["kinds"][0]["win_rate"] is None
    json.dumps(v)                                                                           # plain JSON
    none = SM.owner_views([], [], {}, [], None, None)
    assert none == {"kinds": [], "pairs": {"control": "-ld", "by_role": {}, "recent": []}, "events": []}


def test_determinism_and_no_input_change():
    pa, pb = pairs_example()
    for accts, book, narrowed, rows in (events_example(), (pa, pb, set(), rows_of(pb, pa, (pa[0]["id"],)))):
        for ds in (False, True):
            one = SM.owner_views(LINEUP, accts, book, rows, T0, T0 + 3 * DAY, ds, narrowed, E0)
            frozen = copy.deepcopy((accts, book, rows, narrowed))
            two = SM.owner_views(LINEUP, accts, book, rows, T0, T0 + 3 * DAY, ds, narrowed, E0)
            assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True) and one["events"] + one["pairs"]["recent"]
            assert (accts, book, rows, narrowed) == frozen                                  # nothing was modified
            shuffled = {k: book[k] for k in reversed(list(book))}                           # the book's own order does not matter
            assert SM.owner_views(LINEUP, accts, shuffled, rows, T0, T0 + 3 * DAY, ds, narrowed, E0) == one


# ---------------------------------------------------------------- write_snapshots
def fake_league(tmp_path, owner: bool, name="a.db", ds_scale=1.0):
    """A league object with a real trades table (what write_snapshots reads): kinds fq / sw (main) and ld (control) on a core and a
    DeepSeek pick (its ROE and P&L times ``ds_scale``). ld: 1h-2h SL -10%, 5h-6h TP +20%; fq: 1h-3h RULE +10%, 5h-7h SL +30% with a
    narrowed stop; sw: 1h-2h RULE -10%, then 2h-4h RULE +20% short (its first trade is a switch)."""
    conn = RN.open_db(str(tmp_path / name))
    lu = {r["role"]: r for r in LINEUP}
    accts, book = [], {}
    for pick, kind, name_, tf in ((P1, "core", "DOGE", "15m"), (P2, "ds", "F5_BOX", "1h")):
        for role in ("fq", "sw", "ld"):
            a = {"id": f"{pick}-{role}", "pick": pick, "role": role, "kind": kind, "name": name_, "tf": tf, "combo": {}, "exit": "ladderU|2",
                 "of": pick, "size": 1.0, "source": {}}
            if owner:
                a["ox"] = {**lu[role], "kind": "x", "desc_ko": "d", "why_ko": "w", "tp": None, "weekend_off": False, "size": 1.0, "rule": None}
            accts.append(a)
            book[a["id"]] = []
    narrowed = []
    for pick, kind in ((P1, "core"), (P2, "ds")):
        k = ds_scale if kind == "ds" else 1.0
        for role, ts in (("ld", [(1, 2, "SL", -0.10), (5, 6, "TP", 0.20)]), ("fq", [(1, 3, "RULE", 0.10), (5, 7, "SL", 0.30)]),
                         ("sw", [(1, 2, "RULE", -0.10), (2, 4, "RULE", 0.20)])):
            for e, x, why, roe in ts:
                t = trade("BTCUSDT", -1 if (role, e) == ("sw", 2) else 1, e, x, why, roe * k)
                book[f"{pick}-{role}"].append(t)
                ctx = {"rx_narrowed": 1} if (role, e) == ("fq", 5) else {}
                if ctx:
                    narrowed.append((f"{pick}-{role}", t["entry_time"], t["exit_time"]))
                data = {**t, "entry_price": 100.0, "exit_price": 101.0, "leverage": 10, "stop_initial": 99.0, "tp_price": float("nan"),
                        "mae_price": 99.5, "mfe_price": 101.5, "equity_after": 0.0, "margin": 100.0, "context": ctx}
                conn.execute("INSERT INTO trades VALUES (?, ?, ?)", (f"{pick}-{role}", t["exit_time"], json.dumps(data)))
    conn.commit()
    engines = {a["id"]: SimpleNamespace(position=None, wallet=RN.EQUITY + sum(t["pnl"] for t in book[a["id"]]), bust=False) for a in accts}
    lg = SimpleNamespace(conn=conn, accts=accts, engines=engines, done=T0 + 2 * DAY, start_ms=T0, meta={"started_ms": T0, "notes": []},
                         advanced_ms=None)
    return lg, book, narrowed


NOW = T0 + 2 * DAY + MIN


def test_write_snapshots_carries_the_three_keys_in_the_owner_exit_league(tmp_path):
    lg, book, narrowed = fake_league(tmp_path, True)
    assert SM.narrowed_keys(lg.conn) == set(narrowed) and len(narrowed) == 2               # the two narrowed fq trades, read from the table
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    assert [x["role"] for x in doc["lineup"]] == ["fq", "sw", "ld"]
    assert [k["role"] for k in doc["kinds"]] == ["fq", "sw", "ld"] and [k["group"] for k in doc["kinds"]] == ["main", "main", "control"]
    saved = json.load(open(tmp_path / "snap" / "league.json"))                              # strict JSON on disk, the same as the returned doc
    assert {"kinds", "pairs", "events"} <= set(saved) and all(saved[k] == doc[k] for k in ("kinds", "pairs", "events"))
    fq = saved["kinds"][0]
    assert (fq["accounts"], fq["picks"], fq["trades"], fq["wins"], fq["narrowed_n"], fq["open_now"]) == (2, 2, 4, 4, 2, 0)
    assert fq["trades_per_day"] == pytest.approx(2.0)                                        # 4 trades in the 2 days from the start to the processed time
    assert fq["ds_in_roe"] is True and fq["avg_win_roe"] == pytest.approx(0.2) and fq["mean_roe"] == pytest.approx(0.2)
    assert fq["wallet_return_pct"] == pytest.approx(40 / RN.EQUITY)                          # +10 and +30 on the start wallet
    assert fq["reasons"] == {"SL": 1 * 2, "LOCK": 0, "RULE": 1 * 2, "TP": 0, "LIQ": 0}
    pr = saved["pairs"]                                                                      # fq entered with ld on both picks: +20 and +10 points
    assert pr["control"] == "-ld" and list(pr["by_role"]) == ["fq", "sw"]
    assert (pr["by_role"]["fq"]["n"], pr["by_role"]["fq"]["better"]) == (4, 4) and pr["by_role"]["fq"]["mean_diff_roe"] == pytest.approx(0.15)
    assert (pr["by_role"]["sw"]["n"], pr["by_role"]["sw"]["same"]) == (2, 2) and len(pr["recent"]) == 6   # sw's short at 2h has no control twin
    ev = {(e["account"], e["time"]): e["event"] for e in saved["events"]}
    assert ev[(P1 + "-fq", T0 + 3 * H)] == "rule_exit" and ev[(P1 + "-fq", T0 + 7 * H)] == "narrowed"
    assert ev[(P1 + "-sw", T0 + 2 * H)] == "switch" and ev[(P1 + "-sw", T0 + 4 * H)] == "rule_exit" and len(ev) == 8
    assert [e["time"] for e in saved["events"]] == sorted((e["time"] for e in saved["events"]), reverse=True)
    json.loads(open(tmp_path / "snap" / "league.json").read(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))   # no NaN / Infinity


def test_write_snapshots_hides_deepseek_money_in_the_new_keys(tmp_path):
    """With ds_money off the three keys count the DeepSeek accounts and give none of their ROE, money or returns: making every DeepSeek
    ROE and P&L five times larger (the same wins and losses) changes nothing in them; with the switch on it does."""
    new = ("kinds", "pairs", "events")
    one, _b, _n = fake_league(tmp_path, True, "a.db")
    big, _b, _n = fake_league(tmp_path, True, "b.db", ds_scale=5.0)
    off1 = RN.write_snapshots(str(tmp_path / "s1"), one, NOW, ds_money=False)
    off5 = RN.write_snapshots(str(tmp_path / "s5"), big, NOW, ds_money=False)
    assert all(off1[k] == off5[k] for k in new)
    on1 = RN.write_snapshots(str(tmp_path / "s1"), one, NOW, ds_money=True)
    on5 = RN.write_snapshots(str(tmp_path / "s5"), big, NOW, ds_money=True)
    assert all(on1[k] != on5[k] for k in new)
    # what stays: the counts and the reasons of DeepSeek, its pairs' labels, its events without ROE
    fq = off1["kinds"][0]
    assert (fq["trades"], fq["wins"], fq["narrowed_n"], fq["picks"]) == (4, 4, 2, 2) and fq["ds_in_roe"] is False
    assert fq["avg_win_roe"] == pytest.approx(0.2) and fq["wallet_return_pct"] == pytest.approx(40 / RN.EQUITY)   # the core pick's: +10% and +30%
    assert fq["best_pick"] is None and all(k["ds_in_roe"] is False for k in off1["kinds"])
    r = off1["pairs"]["by_role"]["fq"]
    assert (r["n"], r["n_shown"], r["better"], r["worse"], r["same"]) == (4, 2, 2, 0, 0)
    ds_pairs = [p for p in off1["pairs"]["recent"] if p["kind"] == "ds"]
    assert len(ds_pairs) == 3 and all(p["a_reason"] and p["b_reason"] for p in ds_pairs)
    assert all(p["a_roe"] is None and p["b_roe"] is None and p["diff_roe"] is None for p in ds_pairs)
    assert any(p["a_roe"] is not None for p in off1["pairs"]["recent"] if p["kind"] == "core")
    ds_events = [e for e in off1["events"] if e["kind"] == "ds"]
    assert len(ds_events) == 4 and all(e["roe"] is None and e["control_roe"] is None and e["hold_h"] for e in ds_events)
    assert any(e["roe"] is not None and e["control_roe"] is not None for e in off1["events"] if e["kind"] == "core")


def test_write_snapshots_has_none_of_the_keys_outside_the_owner_exit_league(tmp_path):
    lg, _book, _narrowed = fake_league(tmp_path, False)
    assert RX.lineup(lg.accts) is None
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    for d in (doc, saved):
        assert "lineup" not in d and not ({"kinds", "pairs", "events"} & set(d))


# ---------------------------------------------------------------- /api/judge
FORM = {"content-type": "application/x-www-form-urlencoded", "origin": "http://league.test"}


def test_api_judge_serves_the_data_file_as_it_is(tmp_path, monkeypatch):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32, live=Live(mode="fake")), base_url="http://league.test")
    f = tmp_path / "native_ko.json"
    monkeypatch.setattr(D, "JUDGE_FILE", str(f))
    assert c.get("/api/judge").status_code == 401                                          # the same login as the other /api routes
    f.write_text(json.dumps({"x": 1}))
    assert c.get("/api/judge").status_code == 401
    assert c.post("/login", content="password=pw-123", follow_redirects=False, headers=FORM).status_code == 303
    f.unlink()
    r = c.get("/api/judge")
    assert r.status_code == 200 and r.json() == {}                                         # no file: {}
    doc = {"fq": {"ko": "구조 확실히 무너지면 빠른 손절", "notes": ["하나", "둘"], "n": 3, "x": None}, "sw": {"ko": "스위칭"}}
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = c.get("/api/judge")
    assert r.status_code == 200 and r.json() == doc and r.headers["content-type"].startswith("application/json")
    doc["fq"]["n"] = 4                                                                      # read on every request (the file may be replaced)
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert c.get("/api/judge").json()["fq"]["n"] == 4
    f.write_text("{not json")
    assert c.get("/api/judge").json() == {}                                                # a broken file: {}, not an error page
    assert sorted(os.listdir(snap)) == []                                                  # nothing written
