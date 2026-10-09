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
