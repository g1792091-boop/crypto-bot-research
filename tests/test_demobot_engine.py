"""Demo lab bot engine: grid, exits, cells, ranking helpers, accounts, and a small end-to-end run on a synthetic
market (warm -> ticks -> accounts -> judgment -> snapshots -> restart)."""
import json
import os

import numpy as np
import pytest

from demobot import accounts as A
from demobot import cells as CL
from demobot import data as D
from demobot import engine as EN
from demobot import exits as X
from demobot import grid as G
from demobot import judge as J
from demobot import live as LV
from demobot import rank as RK
from demobot import store as ST
from demobot import costs as CO
from demobot import regime as RG
from demobot import review as RV

M15 = 900_000


def test_grid_counts_and_named_settings():
    assert G.NCOMBO == {"S2_ST_ROC": 343, "N02_ST_KST": 735, "N04_ST_KLINGER": 588}
    assert G.combo_label("S2_ST_ROC", G.default_combo("S2_ST_ROC")) == "ST 10/6 ROC 9"
    assert G.combo_label("S2_ST_ROC", G.friend_combo("S2_ST_ROC")) == "ST 8/3 ROC 37"
    assert G.combo_label("N04_ST_KLINGER", G.friend_combo("N04_ST_KLINGER")) == "ST 8/3 KVOx1 sig 13"
    assert G.combo_label("S2_ST_ROC", G.PICK[("S2_ST_ROC", "15m")]) == "ST 20/6 ROC 5"
    assert len(G.EXITS) == 14 and G.EXITS[5] == "tp1R_sl2atr" and G.exit_stop_k(12) == 3.0
    assert G.EXITS[G.HALFBE] == "half1R_be_1.5R" and G.exit_stop_k(G.HALFBE) == 2.0


def test_accounts_list():
    A.sanity()
    kinds = {}
    for a in A.ACCOUNTS:
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    assert kinds == {"fixed": 16, "adaptive": 24, "friend": 6, "flip": 2}


def test_check_ok_frac_matches_scalar_check():
    rng = np.random.default_rng(3)
    for coin in ("BTCUSD", "DOGEUSD", "LTCUSD"):
        for L in G.LEVS:
            for _ in range(40):
                side = int(rng.choice([1, -1]))
                fill = 100.0
                atr = float(rng.uniform(0.05, 1.5))
                k = float(rng.choice([1.5, 2.0, 3.0]))
                stop_dist = k * atr
                ok, _q, _m, _w = X.entry_check(coin, side, fill, stop_dist, atr, 1000.0, L, minorder=False)
                v = X.check_ok_frac(coin, np.array([side]), np.array([stop_dist / fill]), np.array([atr / fill]), L)[0]
                assert ok == bool(v), (coin, L, side, atr, k)


def _bars(n, seed=0, start=1_780_000_000_000 // M15 * M15, drift=0.0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.003, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.003, n))
    return {"ts": start + np.arange(n, dtype=np.int64) * M15, "o": o, "h": h, "l": lo, "c": c,
            "v": rng.uniform(100, 1000, n)}


def test_cells_placeholder_and_done():
    b = _bars(400, seed=1)
    ts_sig = b["ts"][[100, 398, 399]]
    atr = np.full(3, 0.5)
    r = CL.compute("BTCUSD", "15m", b, ts_sig, np.array([1, 1, -1]), atr, forming=(int(b["ts"][-1] + M15), 123.0))
    assert r["raw"][0] == b["o"][101] and r["raw"][2] == 123.0           # forming bar's open for the last signal
    assert not r["done"][2] and np.isnan(r["F"][2, ST.F_MAIN_R])          # placeholder
    assert r["done"][0] and r["F"][0, ST.F_MAIN_REASON] in (0, 1, 2)
    # an R of the house exit equals the study scan on the same row
    rr = X.run_scan(b, np.array([101]), np.array([1]), np.array([30.0]), np.array([0.03]), np.array([1.0]))
    assert np.isfinite(rr["R"][0])


def test_seg_mdd_bruteforce():
    rng = np.random.default_rng(5)
    seg = np.sort(rng.integers(0, 6, 200))
    r = rng.normal(0, 1, 200)
    starts = np.flatnonzero(np.r_[True, seg[1:] != seg[:-1]])
    got = RK._seg_mdd(starts, r)
    for i, s0 in enumerate(starts):
        s1 = starts[i + 1] if i + 1 < len(starts) else len(r)
        cs = np.r_[0.0, np.cumsum(r[s0:s1])]
        want = float(np.max(np.maximum.accumulate(cs) - cs))
        assert abs(got[i] - want) < 1e-9


class SynthREST:
    """Synthetic Binance: random-walk 15m bars per symbol, funding every 8 h, settable clock."""

    def __init__(self, clock, n=4000, start=None):
        self.clock = clock
        start = start or (1_780_000_000_000 // M15 * M15)
        self.bars = {}
        for i, coin in enumerate(G.COINS):
            b = _bars(n, seed=10 + i, start=start)
            self.bars[G.binance_symbol(coin)] = np.stack([b["ts"], b["o"], b["h"], b["l"], b["c"], b["v"]], 1)

    def klines(self, symbol, interval, start_time=None, limit=1500):
        a = self.bars[symbol]
        a = a[a[:, 0] <= self.clock()]
        a = a[a[:, 0] >= start_time][:limit] if start_time is not None else a[-limit:]
        return [[int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), int(r[0]) + M15 - 1] for r in a]

    def depth(self, symbol, limit=500):
        a = self.bars[symbol]
        a = a[a[:, 0] <= self.clock()]
        mid = float(a[-1][1])
        lv = [(mid * (1 + 1e-4 * (i + 0.5)), 2000.0 / mid * (1 + i)) for i in range(limit)]
        return {"bids": [[2 * mid - p, q] for p, q in lv], "asks": [[p, q] for p, q in lv]}

    def funding_rates(self, symbol, start_time=None, limit=1000):
        t0 = int(self.bars[symbol][0, 0]) // 28_800_000 * 28_800_000
        ts = np.arange(t0, self.clock(), 28_800_000)
        if start_time is not None:
            ts = ts[ts >= start_time]
        return [{"fundingTime": int(t), "fundingRate": "0.0001"} for t in ts[:limit]]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    old = EN.WARMUP_15M
    EN.WARMUP_15M = 400
    start = 1_780_000_000_000 // M15 * M15
    clock = [start + 1300 * M15 + 25_000]
    rest = SynthREST(lambda: clock[0], n=2000, start=start)
    mkt = D.Market(rest=rest, clock_ms=lambda: clock[0], pause=lambda s: None)
    conn = ST.connect(str(d / "demo.db"))
    os.environ["DEMOBOT_DB"] = str(d / "demo.db")
    eng = EN.Engine(conn, market=mkt, clock_ms=lambda: clock[0], log=lambda *a: None)
    out = eng.warm(weeks=0.7, end_ms=clock[0])
    r = LV.Runner(conn, market=mkt, snap=str(d / "snap"), clock_ms=lambda: clock[0], token="", chat="",
                  logf=lambda *a: None)
    r.outbox = None
    r.start()
    infos = []
    for _ in range(3):
        clock[0] += M15
        infos.append(r.tick())
    RK.run_standalone(conn, str(d / "snap"), clock[0], log=lambda *a: None)
    yield dict(dir=d, conn=conn, runner=r, clock=clock, mkt=mkt, warm=out, infos=infos)
    EN.WARMUP_15M = old


def test_end_to_end_snapshots(run):
    snap = run["dir"] / "snap"
    for f in ("status.json", "accounts.json", "trades.json", "judge.json", "home.json", "rank_meta.json"):
        assert (snap / f).exists(), f
    for info in run["infos"]:
        assert info["errors"] == []
    acc = json.loads((snap / "accounts.json").read_text())
    assert len(acc["accounts"]) == 48
    for a in acc["accounts"]:
        assert set(a["lines"]) == {"20", "30", "40", "50"}
        assert (snap / "acct" / f"{a['id']}.json").exists()
    z = np.load(snap / "rank_S2_15m.npz")
    assert z["stats"].shape == (3, G.NEXIT, 8, 343, len(RK.K_STATS))
    st = json.loads((snap / "status.json").read_text())
    assert st["phase"] == "live" and st["counts"]["settings"] == 1666
    jd = json.loads((snap / "judge.json").read_text())
    assert len(jd["rows"]) == 48 * 4 and "실전 금지" in jd["verdict_ko"]


def test_restart_replays_same_accounts(run):
    conn = run["conn"]
    snap = run["dir"] / "snap"
    before = json.loads((snap / "accounts.json").read_text())
    r2 = LV.Runner(conn, market=run["mkt"], snap=str(snap), clock_ms=lambda: run["clock"][0], token="", chat="",
                   logf=lambda *a: None)
    r2.outbox = None
    r2.start()
    res = A.run_all(r2.eng, run["clock"][0])
    for a in before["accounts"]:
        for L in G.LEVS:
            got = res[a["id"]]["lines"][L]["line"]
            want = a["lines"][str(L)]
            assert got["trades"] == want["trades"] and abs(got["equity"] - want["equity"]) < 1e-6, (a["id"], L)


def test_live_signals_equal_full_series(run):
    from demobot import locked as LK
    eng = run["runner"].eng
    live0 = eng.live_start
    for coin in G.COINS[:2]:
        for tf in G.TFS:
            bt = eng.bars_tf(coin, tf)
            df = LK.frame(bt["ts"], bt["o"], bt["h"], bt["l"], bt["c"], bt["v"], tf)
            pos = np.flatnonzero(bt["ts"] + G.TF_MIN[tf] * 60000 >= live0)
            for s in G.STRATS:
                full = LK.grid_sides(s, df, tf)[:, pos]
                ts, cb, sd = eng.sigs[(coin, tf, s)].arrays()
                for j, p in enumerate(pos):
                    live = np.zeros(G.NCOMBO[s], np.int8)
                    m = ts == bt["ts"][p]
                    live[cb[m]] = sd[m]
                    assert np.array_equal(live, full[:, j]), (coin, tf, s, j)


def test_standalone_rank_equals_inline(run):
    """The rank process (database view) gives the same arrays as the in-process engine state."""
    eng = run["runner"].eng
    now = run["clock"][0]
    a = RK.compute(eng, "N02_ST_KST", "30m", now)
    z = np.load(run["dir"] / "snap" / "rank_N02_30m.npz")
    assert np.allclose(a["stats"], z["stats"], equal_nan=True)
    assert np.allclose(a["luck95"], z["luck95"], equal_nan=True)


def test_rank_counts_match_signal_lookup(run):
    """n and mean R of the default setting (house exit, all coins, 26w window) equal a direct lookup."""
    eng = run["runner"].eng
    now = run["clock"][0]
    strat, tf = "S2_ST_ROC", "15m"
    r = RK.compute(eng, strat, tf, now)
    c = G.default_combo(strat)
    vals = []
    lo = now - 26 * 7 * 86400 * 1000
    for coin in G.COINS:
        ts, cb, sd = eng.sigs[(coin, tf, strat)].arrays()
        m = (cb == c) & (ts >= lo - lo % M15)
        book = eng.books[(coin, tf)]
        k = book.index(ts[m])
        s = np.where(sd[m] > 0, 0, 1)
        ok = k >= 0
        R = book.F[k[ok], s[ok], ST.F_MAIN_R]
        d = book.F[k[ok], s[ok], ST.F_MAIN_REASON] != 3
        vals.extend(R[d].tolist())
    st = r["stats"][1, 0, 0, c]
    assert int(st[0]) == len(vals)
    if vals:
        assert abs(float(st[2]) - float(np.mean(vals))) < 1e-5


PLUGIN_SRC = '''
KEY = "t1"
ACCOUNTS = [{"variant": "x", "name": "시험 플러그인", "rule_ko": "시험", "tf": "15m"}]
def trades(variant, bars15, start_ms, now_ms):
    b = bars15["BTCUSD"]
    import numpy as np
    i = int(np.searchsorted(b["ts"], start_ms))
    if i + 2 >= len(b["ts"]):
        return []
    e = float(b["o"][i]); stop = e * 0.99
    return [dict(coin="BTCUSD", side=1, signal_ms=int(b["ts"][i]) - 900000, entry_ms=int(b["ts"][i]), entry=e,
                 stop=stop, atr=None, maker_entry=True,
                 legs=[(0.5, int(b["ts"][i + 1]), e * 1.01, "tp"), (0.5, int(b["ts"][i + 2]), e, "be")],
                 setting_ko="시험", exit_ko="시험")]
'''


def test_private_plugin_accounts(run, tmp_path, monkeypatch):
    d = tmp_path / "plugins"
    d.mkdir()
    (d / "t1.py").write_text(PLUGIN_SRC)
    (d / "broken.py").write_text("KEY = 'Bad Key'\n")
    monkeypatch.setenv("DEMOBOT_PLUGINS", str(d))
    eng = run["runner"].eng
    res = A.run_all(eng, run["clock"][0], log=lambda *a: None)
    assert "pv-t1-x" in res and all(L in res["pv-t1-x"]["lines"] for L in G.LEVS)
    line = res["pv-t1-x"]["lines"][20]
    tr = [t for t in line["trades"]]
    assert len(tr) == 1 and tr[0]["status"] == "closed" and tr[0]["reason"] == "be"
    # half at +1% (maker), half at break-even: positive before costs, R about 0.5 minus fees
    assert 0.3 < tr[0]["R"] < 0.5
    jd = J.judge_all(res, run["clock"][0])
    assert any(r["id"] == "pv-t1-x" for r in jd["rows"])
    monkeypatch.setenv("DEMOBOT_PLUGINS", str(tmp_path / "none"))
    A.refresh_plugins(log=lambda *a: None)
    assert not any(a.kind == "private" for a in A.current_accounts())


# ------------------------------------------------------------------ round 3 (CONTRACT section 8)
def test_stop_rules_unit():
    day0 = 1_789_000_000_000 // 86_400_000 * 86_400_000 - 9 * 3_600_000 + 86_400_000   # a KST midnight
    r = A.StopRules(20)
    assert not r.block(day0 + 1000, 1000.0)
    # five losses in a row -> 24 h pause from the 5th close
    W = 1000.0
    for i in range(5):
        r.on_close(day0 + (i + 1) * M15, -2.0, W, W - 2.0)
        W -= 2.0
    assert r.streak_pauses == 1 and r.block(day0 + 6 * M15, W)
    assert not r.block(day0 + 5 * M15 + 24 * 3_600_000 + 1, W)
    # -5% of the day's first wallet -> blocked until the next KST midnight
    r2 = A.StopRules(20)
    r2.block(day0 + 1000, 1000.0)
    r2.on_close(day0 + 2 * M15, -30.0, 1000.0, 970.0)
    assert not r2.block(day0 + 3 * M15, 970.0)
    r2.on_close(day0 + 4 * M15, -25.0, 970.0, 945.0)
    assert r2.day_pauses == 1 and r2.block(day0 + 5 * M15, 945.0)
    assert not r2.block(day0 + 86_400_000 + 1, 945.0)
    # -20% of the start -> never again
    r3 = A.StopRules(50)
    r3.on_close(day0 + M15, -210.0, 1000.0, 790.0)
    assert r3.halted_ms == day0 + M15
    assert r3.block(day0 + 400 * 86_400_000, 2000.0)
    assert [e["what"] for e in r3.events] == ["day", "halt"]


def test_costs_book_walk_and_interpolation():
    asks = [[100.1, 10.0], [100.2, 10.0], [100.5, 100.0]]
    bids = [[99.9, 10.0], [99.8, 10.0]]
    assert abs(CO.book_cost_bps(asks, 500, 100.0) - 10.0) < 1e-9          # one level: half the spread = 10 bp
    two = CO.book_cost_bps(asks, 1503, 100.0)                             # 1001 + 502 USD over two levels
    assert 10.0 < two < 20.0
    assert CO.book_cost_bps(bids, 10_000, 100.0) is None                  # the book does not cover it
    bid, ask, buy, sell = CO.curve_from_depth({"bids": bids, "asks": asks})
    assert (bid, ask) == (99.9, 100.1) and len(buy) == len(CO.SIZES) and buy[0] == pytest.approx(10.0)
    curve = [1.0, 2.0, 3.0] + [None] * (len(CO.SIZES) - 3)
    assert CO.interp_bps(curve, 250) == 1.0 and CO.interp_bps(curve, 750) == pytest.approx(1.5)
    assert CO.interp_bps(curve, 1500) == pytest.approx(2.5) and CO.interp_bps(curve, 3000) is None


def test_regime_trend_on_a_steady_rise():
    n = 96 * 120
    ts = (1_780_000_000_000 // M15 * M15) + np.arange(n, dtype=np.int64) * M15
    c = 100 * np.exp(np.linspace(0, 1.0, n)) * (1 + 0.002 * np.sin(np.arange(n)))
    b = {"ts": ts, "o": np.r_[c[0], c[:-1]], "h": c * 1.002, "l": c * 0.998, "c": c}
    tr, vo, sl, _ap = RG.coin_regime(b)
    assert tr[0] == RG.UNK and tr[-1] == 1 and sl[-1] > RG.SLOPE_T
    assert vo[0] == RG.UNK and vo[-1] in (0, 1, 2)
    flat = dict(b, c=np.full(n, 100.0), o=np.full(n, 100.0), h=np.full(n, 100.2), l=np.full(n, 99.8))
    assert RG.coin_regime(flat)[0][-1] == 0


def test_week_boundaries_are_kst_mondays():
    t = 1_791_000_000_000
    w = RV.week_start(t)
    import time as _t
    g = _t.gmtime((w + 9 * 3_600_000) / 1000)
    assert g.tm_wday == 0 and g.tm_hour == 0 and g.tm_min == 0 and w <= t < w + RV.WEEK_MS


def _fake_line(trades):
    return {"line": {}, "trades": trades, "curve": []}


def test_confirmation_period(tmp_path):
    conn = ST.connect(str(tmp_path / "c.db"))
    aid, L, t0 = "fx-def-S2-15m", 20, 1_790_000_000_000
    D = 86_400_000
    good = [dict(entry_ms=t0 + i * D, exit_ms=t0 + i * D + 3_600_000, status="closed", reason="tp", pnl=5.0, R=0.5)
            for i in range(25)]
    res = {aid: {"lines": {L: _fake_line(good)}}}
    rows = [dict(id=aid, L=L, ours={"pass": True})]
    out = J.update_confirms(conn, res, rows, t0)
    assert len(out["started"]) == 1 and out["items"][0]["status"] == "confirming"
    out = J.update_confirms(conn, res, [dict(id=aid, L=L, ours={"pass": False})], t0 + 10 * D)
    assert out["items"][0]["status"] == "confirming" and not out["started"]          # a flicker does not restart
    out = J.update_confirms(conn, res, [dict(id=aid, L=L, ours={"pass": False})], t0 + 28 * D + 1)
    assert out["items"][0]["status"] == "confirmed" and len(out["decided"]) == 1
    # a losing line fails and may start again on its next pass
    aid2 = "fx-def-N02-15m"
    bad = [dict(g, pnl=-5.0, R=-0.5) for g in good]
    res[aid2] = {"lines": {L: _fake_line(bad)}}
    J.update_confirms(conn, res, [dict(id=aid2, L=L, ours={"pass": True})], t0)
    out = J.update_confirms(conn, res, [dict(id=aid2, L=L, ours={"pass": False})], t0 + 28 * D + 1)
    it = next(x for x in out["items"] if x["id"] == aid2)
    assert it["status"] == "failed" and "평균 R" in it["why_ko"]
    out = J.update_confirms(conn, res, [dict(id=aid2, L=L, ours={"pass": True})], t0 + 30 * D)
    assert any(p["acct"] == aid2 for p in out["started"])
    # too few trades: waits up to 56 days, then fails
    aid3 = "fx-def-N04-15m"
    res[aid3] = {"lines": {L: _fake_line(good[:5])}}
    J.update_confirms(conn, res, [dict(id=aid3, L=L, ours={"pass": True})], t0)
    out = J.update_confirms(conn, res, [dict(id=aid3, L=L, ours={"pass": False})], t0 + 30 * D)
    assert next(x for x in out["items"] if x["id"] == aid3)["status"] == "confirming"
    out = J.update_confirms(conn, res, [dict(id=aid3, L=L, ours={"pass": False})], t0 + 56 * D)
    assert next(x for x in out["items"] if x["id"] == aid3)["status"] == "failed"


def test_round3_snapshots(run):
    snap = run["dir"] / "snap"
    for f in ("costs.json", "regime.json", "review.json"):
        assert (snap / f).exists(), f
    for coin in G.COINS:
        z = np.load(snap / "bars" / f"{coin}.npz")
        assert set(z.files) == {"ts", "o", "h", "l", "c"} and len(z["ts"]) > 0
    acc = json.loads((snap / "accounts.json").read_text())
    for a in acc["accounts"]:
        for L, ln in a["lines"].items():
            p = ln["parts"]
            assert abs(p["gross"] - p["fees"] + p["funding"] + p["open"] - ln["pnl"]) < 1e-6
            st = ln["stops"]
            assert st["blocked"] >= 0 and st["trades"] <= ln["trades"] + st["blocked"] + ln["open"] + 50
    d = json.loads((snap / "acct" / "fx-def-S2-15m.json").read_text())
    assert set(d["curves_stops"]) == {"20", "30", "40", "50"} and isinstance(d["stop_events"], list)
    for t in d["trades"]:
        assert {"fee", "notional", "cost_bps", "through_bps", "trend", "vol"} <= set(t)
    jd = json.loads((snap / "judge.json").read_text())
    assert jd["lines_judged"] == 48 * 4 and len(jd["stop_rules_ko"]) == 3 and "passed" not in jd
    assert all("stops" in r and "confirm" in r for r in jd["rows"])
    home = json.loads((snap / "home.json").read_text())
    assert home["goal"]["stage"] == 1 and home["goal"]["days_left"] >= 0 and "12/31" in home["goal"]["line_ko"]
    assert {"confirming", "candidates"} <= set(home["totals"])
    c = json.loads((snap / "costs.json").read_text())
    assert c["sizes"] == CO.SIZES and len(c["coins"]) == 7 and c["coins"][0]["n"] >= 1
    assert c["coins"][0]["buy_bps"]["last"][0] == pytest.approx(0.5, abs=0.05)     # the synthetic book: 0.5 bp
    rv = json.loads((snap / "review.json").read_text())
    assert rv["weeks"] and rv["weeks"][0]["final"] is False and rv["weeks"][0]["summary_ko"]
    st = json.loads((snap / "status.json").read_text())
    assert st["deadman"]["configured"] is False


def test_deadman_ping():
    class Resp:
        def __init__(self, code):
            self.status = code

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert LV.ping_deadman("https://hc-ping.com/x", opener=lambda req, timeout: Resp(200)) is None
    assert LV.ping_deadman("https://hc-ping.com/x", opener=lambda req, timeout: Resp(503)) == "HTTP 503"

    def boom(req, timeout):
        raise OSError("no route https://hc-ping.com/secret")
    assert LV.ping_deadman("https://hc-ping.com/secret", opener=boom) == "OSError"
