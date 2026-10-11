"""candleague/summary.py (the 점검 진행 data, research/fullgrid/WATCH_PREREG.md 2-3): a pool's mean is over all of its
closed trades in the wallet-before unit; the C1 stop rule and the C2 conditions; UTC weeks from Monday; the preview p is
the study's week bootstrap and reproducible; DeepSeek money stays out unless shown; the checkpoint dates are the
pre-registered ones. Also candleague/data/strategies_ko.json against the strategies' real parameters."""

from __future__ import annotations

import datetime
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import candidates as C  # noqa: E402
from candleague import summary as SM  # noqa: E402

UTC = datetime.timezone.utc
MON = int(datetime.datetime(2026, 10, 5, tzinfo=UTC).timestamp() * 1000)        # a Monday 00:00 UTC
DAY = 86_400_000


def _accts(kind="core", name="S2_ST_ROC", tf="15m", cid="c1"):
    return [{"id": cid, "role": "cand", "kind": kind, "name": name, "tf": tf},
            {"id": f"{cid}-q", "role": "quarter", "kind": kind, "name": name, "tf": tf},
            {"id": f"{cid}-x", "role": "exitonly", "kind": kind, "name": name, "tf": tf},
            {"id": f"base-{kind}-{name}-{tf}", "role": "base", "kind": kind, "name": name, "tf": tf},
            {"id": f"{cid}-flip", "role": "flip", "kind": kind, "name": name, "tf": tf}]


def _trades(pnls, t0=MON, step=DAY):
    return [{"exit_time": t0 + i * step, "pnl": p} for i, p in enumerate(pnls)]


def test_returns_are_per_wallet_before():
    r = SM.returns(_trades([500.0, -550.0]))
    assert [round(x, 6) for _, x in r] == [0.1, -0.1]                   # 500 / 5000, then -550 / 5500


def test_week_starts_monday_utc():
    assert SM.week_of(MON) == MON and SM.week_of(MON + 7 * DAY - 1) == MON and SM.week_of(MON + 7 * DAY) == MON + 7 * DAY
    assert SM.week_of(MON - 1) == MON - 7 * DAY
    assert datetime.datetime.fromtimestamp(SM.week_of(MON + 3 * DAY) / 1000, UTC).weekday() == 0


def test_pool_mean_is_over_all_trades_and_c1_c2():
    accts = _accts() + _accts(cid="c2", name="N03_ADX_GC")
    book = {"c1": _trades([100.0] * 3), "c2": _trades([-50.0]),                 # cand pool: 4 trades
            "base-core-S2_ST_ROC-15m": _trades([-10.0]), "base-core-N03_ADX_GC-15m": _trades([-10.0]),
            "c1-flip": _trades([20.0]), "c2-flip": _trades([-200.0])}
    w = SM.watch_summary(accts, book, MON + 30 * DAY)
    p = w["pools"]["core"]
    ret_c1 = SM.returns(book["c1"])
    want = (sum(x for _, x in ret_c1) + (-50.0 / 5000)) / 4
    assert abs(p["roles"]["cand"]["mean"] - want) < 1e-12 and p["roles"]["cand"]["n"] == 4 and p["roles"]["cand"]["wins"] == 3
    assert p["c1_stop"] is False and p["c2"]["positive"] and p["c2"]["beats_base"] and p["c2"]["beats_flip"] is True
    assert p["c2"]["enough"] is False and p["c2"]["all"] is False and p["picks"] == 2 and p["accounts"] == 10
    assert w["pools"]["ds"]["roles"]["cand"]["n"] == 0 and w["pools"]["ds"]["c1_stop"] is None
    # the stop rule: below both
    book2 = dict(book, c1=_trades([-100.0]), c2=_trades([-100.0]), **{"c1-flip": _trades([10.0]), "c2-flip": _trades([10.0])})
    assert SM.watch_summary(accts, book2, MON + 30 * DAY)["pools"]["core"]["c1_stop"] is True
    s = w["strategies"]["S2_ST_ROC"]
    assert s["n"] == 3 and s["positive"] and s["tfs"] == ["15m"] and "mean" in s


def test_p_needs_four_weeks_and_is_reproducible():
    accts = _accts()
    book = {"c1": _trades([30.0, -10.0] * 20, step=DAY // 2)}                 # 40 trades over 20 days: 3 weeks
    w = SM.watch_summary(accts, book, MON + 60 * DAY)
    assert w["pools"]["core"]["c2"]["weeks"] == 3 and w["pools"]["core"]["c2"]["p"] is None
    book = {"c1": _trades([30.0, -10.0] * 20, step=DAY)}                      # 40 days: 6 weeks
    a, b = (SM.watch_summary(accts, book, MON + 60 * DAY)["pools"]["core"]["c2"] for _ in range(2))
    assert a["weeks"] == 6 and a["p"] is not None and a["p"] == b["p"] and a["p"] < 0.05 and a["p_ok"]
    rr = SM.returns(book["c1"])
    seed = SM._seed("watch", "core", datetime.datetime.fromtimestamp((MON + 60 * DAY) / 1000, UTC).strftime("%Y-%m-%d"))
    assert a["p"] == SM.boot_mean_p(np.array([SM.week_of(t) for t, _ in rr]), np.array([x for _, x in rr]), SM.N_BOOT, seed)


def test_deepseek_money_hidden_unless_shown():
    accts = _accts(kind="ds", name="F5_BOX")
    book = {"c1": _trades([30.0, -10.0] * 20, step=DAY), "c1-flip": _trades([-5.0] * 3)}
    hid = SM.watch_summary(accts, book, MON + 60 * DAY)
    p = hid["pools"]["ds"]
    assert all(p["roles"][r]["mean"] is None for r in SM.ROLES) and "p" not in p["c2"] and p["money"] is False
    assert p["c2"]["positive"] is True and p["c2"]["p_ok"] is True and p["roles"]["cand"]["n"] == 40
    assert all(w[r]["sum"] is None for w in p["weeks"] for r in ("cand", "base", "flip"))
    assert "mean" not in hid["strategies"]["F5_BOX"] and hid["strategies"]["F5_BOX"]["beats_flip"] is True
    txt = json.dumps(hid["pools"]["ds"])
    assert '"mean": null' in txt and '"sum": null' in txt
    shown = SM.watch_summary(accts, book, MON + 60 * DAY, ds_money=True)["pools"]["ds"]
    assert shown["roles"]["cand"]["mean"] is not None and shown["c2"]["p"] is not None and shown["money"] is True


def test_checkpoint_dates_are_the_preregistered_ones():
    txt = open(os.path.join(ROOT, "research", "fullgrid", "WATCH_PREREG.md")).read()
    for c in SM.CHECKPOINTS[:2]:
        assert c["date"] in txt
    assert "2027-01-11" in txt and SM.CHECKPOINTS[2]["date"] == "2027-01-11"
    assert SM.POOL_MIN_TRADES == 300 and SM.N_BOOT == 2000 and "300 closed" in txt and "2,000 resamples" in txt
    w = SM.watch_summary(_accts(), {}, SM.day_ms("2026-11-10"))
    assert [round(c["days_left"]) for c in w["checkpoints"]] == [1, 31, 62]


def test_strategy_names_file_matches_the_strategies():
    m = json.load(open(os.path.join(ROOT, "candleague", "data", "strategies_ko.json")))
    cands = C.load(C.DEFAULT_FILE)
    assert set(m["picks"]) == {c["id"] for c in cands} and len(m["picks"]) == 38
    assert set(m["strategies"]) == {c["name"] for c in cands} and len(m["strategies"]) == 16
    for name, s in m["strategies"].items():
        kind = "ds" if name.startswith("F") else "core"
        assert s["kind"] == kind and s["ko"] and s["long"] and s["short"]
        real = C.params_of(kind, name)
        assert [p["name"] for p in s["params"]] == [p["name"] for p in real], name
        assert [p["default"] for p in s["params"]] == [p["default"] if not isinstance(p["default"], tuple) else list(p["default"])
                                                         for p in real], name
    by_kind = {c["id"]: c["kind"] for c in cands}
    styles = [p["style"] for p in m["picks"].values()]
    assert styles.count("trend") == 28 and styles.count("mixed") == 7 and styles.count("reversal") == 3
    for pid, p in m["picks"].items():
        if by_kind[pid] == "ds":                                             # no DeepSeek money figure in the repository
            assert all("mean" not in st for st in p["states"].values()), pid


def test_side_and_coin_splits():
    accts = _accts() + _accts(kind="ds", name="F5_BOX", cid="d1")
    t = [{"exit_time": MON + i * DAY, "pnl": p, "side": sd, "symbol": sym}
         for i, (p, sd, sym) in enumerate([(100.0, 1, "BTCUSDT"), (-50.0, -1, "ETHUSDT"), (200.0, -1, "ETHUSDT")])]
    w = SM.watch_summary(accts, {"c1": t, "d1": t}, MON + 30 * DAY)
    sp = w["picks"]["c1"]
    assert sp["long"]["n"] == 1 and sp["short"]["n"] == 2 and sp["short"]["wins"] == 1
    assert abs(sp["long"]["mean"] - 0.02) < 1e-12 and set(sp["coins"]) == {"BTC", "ETH"} and sp["coins"]["ETH"]["n"] == 2
    assert w["pools"]["core"]["sides"]["short"]["n"] == 2 and w["pools"]["core"]["sides"]["long"]["mean"] is not None
    hid = w["picks"]["d1"]
    assert hid["short"]["n"] == 2 and hid["short"]["mean"] is None and hid["coins"]["ETH"]["mean"] is None
    assert w["pools"]["ds"]["sides"]["long"]["mean"] is None
    assert SM.watch_summary(accts, {"c1": t, "d1": t}, MON, ds_money=True)["picks"]["d1"]["short"]["mean"] is not None


def _watch_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location("watch_check", os.path.join(ROOT, "research", "fullgrid", "diag", "watch_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_checkpoint_script_matches_the_dashboard_and_the_rules():
    """research/fullgrid/diag/watch_check.py (WATCH_PREREG 5) from a trades.json-like book: the same pool numbers as the
    dashboard's summary, only trades before the checkpoint date, DeepSeek without money refused, BH over strategies."""
    WC = _watch_check()
    accts = _accts() + _accts(cid="c2", name="N03_ADX_GC")
    pn = {"c1": [30.0, -10.0] * 15, "c2": [-20.0, 25.0] * 10, "base-core-S2_ST_ROC-15m": [5.0, -6.0] * 8,
          "base-core-N03_ADX_GC-15m": [1.0] * 4, "c1-flip": [-3.0] * 6, "c2-flip": [2.0, -9.0] * 3, "c1-x": [4.0] * 3}
    trades = {k: _trades(v, step=DAY // 2) for k, v in pn.items()}

    def eq(rows):
        w, out = 5000.0, [[MON - DAY, 5000.0]]
        for t in rows:
            w += t["pnl"]
            out.append([t["exit_time"], round(w, 2)])
        return out
    book = {a["id"]: {"equity": eq(trades.get(a["id"], [])), "trades": []} for a in accts}
    date = "2026-11-11"
    res = WC.check({"accounts": accts}, book, date)
    summ = SM.watch_summary(accts, trades, SM.day_ms(date))
    for r in SM.ROLES:
        a, b = res["pools"]["core"]["roles"][r], summ["pools"]["core"]["roles"][r]
        assert a["n"] == b["n"] and a["wins"] == b["wins"]
        assert (a["mean"] is None and b["mean"] is None) or abs(a["mean"] - b["mean"]) < 1e-6
    assert res["pools"]["core"]["c1_stop"] == summ["pools"]["core"]["c1_stop"] is False
    assert res["pools"]["core"]["c2"]["trades_300"] is False and res["pools"]["core"]["c2"]["pass"] is False
    assert res["checkpoint"] == "C1" and set(res["strategies"]) == {"S2_ST_ROC", "N03_ADX_GC"}
    # a date before some trades counts only the earlier ones
    early = WC.check({"accounts": accts}, book, "2026-10-08")
    assert 0 < early["pools"]["core"]["roles"]["cand"]["n"] < res["pools"]["core"]["roles"]["cand"]["n"]
    # DeepSeek with its money hidden in the snapshot: refused, never computed from nothing
    ds = _accts(kind="ds", name="F5_BOX", cid="d1")
    hid = WC.check({"accounts": accts + ds}, dict(book, **{a["id"]: {"equity": None, "trades": []} for a in ds}), date)
    assert "error" in hid["pools"]["ds"] and hid["strategies"] == {} and "strategies_error" in hid
    assert WC.bh([0.001, 0.2, 0.03, None]) == [True, False, True, False]


def test_checkpoint_strategy_rule_and_completeness():
    """Per strategy (WATCH_PREREG 3.5, the reading in DEVIATIONS.md): C2's three conditions incl. 300 trades, BH over
    the 16 (p = 1 under 300); a few lucky trades never pass; numbers before the league reached the date are not final."""
    WC = _watch_check()
    accts = _accts() + _accts(cid="c2", name="N03_ADX_GC")
    few = _trades([50.0] * 12, step=DAY // 2)                       # 12 winning trades: bootstrap p would be tiny
    many = _trades([40.0, -15.0] * 160, step=DAY // 8)              # 320 trades, mostly up
    book_tr = {"c1": few, "c2": many, "base-core-S2_ST_ROC-15m": _trades([-5.0] * 5), "base-core-N03_ADX_GC-15m": _trades([-5.0] * 5),
               "c1-flip": _trades([-5.0] * 5), "c2-flip": _trades([-5.0] * 5)}

    def eq(rows):
        w, out = 5000.0, [[MON - DAY, 5000.0]]
        for t in rows:
            w += t["pnl"]
            out.append([t["exit_time"], round(w, 2)])
        return out
    book = {a["id"]: {"equity": eq(book_tr.get(a["id"], [])), "trades": []} for a in accts}
    res = WC.check({"accounts": accts, "done_ms": SM.day_ms("2026-12-11")}, book, "2026-12-11")
    s1, s2 = res["strategies"]["S2_ST_ROC"], res["strategies"]["N03_ADX_GC"]
    assert s1["trades_300"] is False and s1["p"] == 1.0 and s1["pass"] is False
    assert s2["trades_300"] is True and s2["p"] < 0.05 and s2["positive_p"] and s2["bh_10"] and s2["pass"] is True
    assert res["complete"] is True
    late = WC.check({"accounts": accts, "done_ms": SM.day_ms("2026-12-10")}, book, "2026-12-11")
    assert late["complete"] is False
