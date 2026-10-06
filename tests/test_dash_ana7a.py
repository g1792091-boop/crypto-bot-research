"""ana7a (분석 additions): 좋은 수치 찾기 (/api/v4/indranges: the committed 5-year result + the paper run's entries),
강제청산 직후 (/api/v4/liqentry), 들고 있었다면 / 반대로 했다면 (/api/v4/holdcmp) and GH Coin과 같은 방향 (/api/v4/ghagree).
Read-only and descriptive: the math on hand-made cases, the committed JSON's own rules, the waiting states (filling
bars, never a table of zeros), DeepSeek with counts and shares only, the endpoint shapes, nothing written to any
database, and the cards rendered in node with the ana-syn tiny DOM (tests/anasyn_dom.mjs)."""
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ana7a_world import build_all, fake_frames  # noqa: E402
from anasyn_world import DAY, HOUR, MIN, blank, kst, trade  # noqa: E402
from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.more import a7kit as K  # noqa: E402
from paperbot.dash.more import ghagree as GA  # noqa: E402
from paperbot.dash.more import holdcmp as HC  # noqa: E402
from paperbot.dash.more import indranges as IR  # noqa: E402
from paperbot.dash.more import liqentry as LE  # noqa: E402
from paperbot.dash.tools import indcore as IC  # noqa: E402
from paperbot.dash.tools import indranges as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
T0 = kst(2026, 10, 6, 3, 35)
DS_MONEY = {"mean_roe", "roe", "mean_r", "ret", "mirror_ret", "curve", "pnl", "equity", "realized", "pnl_sum"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _read(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as f:
        return f.read()


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    folder = str(tmp_path_factory.mktemp("a7w"))
    info = build_all(folder, days=12, hours=20)
    now = info["now"]
    views = {"paper": IR.paper_view(info["db"], now, fake_frames()),
             "liq": {g: LE.view(info["db"], now, g) for g in ("core", "ds200", "reel")},
             "hold": {g: HC.view(info["db"], now, g, fake_frames()) for g in ("core", "ds200", "reel")},
             "gh": {g: GA.view(info["db"], now, g) for g in ("core", "ds200", "reel")}}
    return {**info, "folder": folder, **views}


# ---------------------------------------------------------------- indcore: ranges by hand
def test_ranges_by_hand():
    e = IC.edges_of(np.arange(100, dtype=float))
    assert e == pytest.approx([19.8, 39.6, 59.4, 79.2])
    assert IC.q_idx([0, 19.8, 20, 59.4, 99, np.nan], e).tolist() == [0, 1, 1, 3, 4, -1]   # an edge value goes up
    assert IC.q_idx([1, 2], None).tolist() == [-1, -1] and IC.edges_of([1.0] * 49) is None
    assert IC.sided("rsi", [70, 70], [1, -1]).tolist() == [70, 30]             # a short reads 100 - RSI
    assert IC.sided("ema200", [2.0, 2.0], [1, -1]).tolist() == [2.0, -2.0]
    assert IC.sided("adx", [30, 30], [1, -1]).tolist() == [30, 30]
    assert IC.funding_idx([-0.0001, 0.0, 0.0001, 0.00011, np.nan]).tolist() == [0, 1, 1, 2, -1]
    # Korea-time sessions: 09-16 asia, 16-22 europe, 22-05 us, 05-09 dawn (paperbot/sessions.py)
    hours = [9, 15, 16, 21, 22, 4, 5, 8]
    ms = [kst(2026, 10, 6, h) for h in hours]
    assert IC.session_idx(ms).tolist() == [0, 0, 1, 1, 2, 2, 3, 3]
    from paperbot.sessions import SESSIONS, session_of
    assert [IC.FIXED["session"][IC.session_of_hour(h)] for h in range(24)] == [session_of(h) for h in range(24)]
    assert set(IC.FIXED["session"]) == set(SESSIONS)
    t = np.array([0, 8 * HOUR, 16 * HOUR], np.int64)
    got = IC.funding_at(t, np.array([0.1, 0.2, 0.3]), [HOUR, 8 * HOUR, 26 * HOUR, -1])
    assert got[:2].tolist() == [0.1, 0.2] and math.isnan(got[2]) and math.isnan(got[3])   # 10 h old / before: unknown


def test_entry_numbers_use_the_locked_indicator_code():
    from paperbot import sweepsig
    import pandas as pd
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    o = np.r_[c[0], c[:-1]]
    h, lo, v = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998, rng.lognormal(3, 0.4, 400)
    s = IC.series(o, h, lo, c, v)
    fg = sweepsig.lib().fg
    df = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c})
    i = 350
    atr = fg.atr(df, 14).to_numpy()[i]
    assert s["rsi"][i] == pytest.approx(fg.rsi(df["close"], 14).to_numpy()[i])
    assert s["atr_pct"][i] == pytest.approx(atr / c[i])
    assert s["ema200"][i] == pytest.approx((c[i] - fg.ema(df["close"], 200).to_numpy()[i]) / atr)
    assert s["vol"][i] == pytest.approx(v[i] / v[i - 20:i].mean())                 # the 20 bars BEFORE the signal bar
    assert s["bbw"][i] == pytest.approx(4 * c[i - 19:i + 1].std() / c[i - 19:i + 1].mean() * 100)
    assert np.isnan(s["ema200"][150])                                              # EMA200 not settled: no number


# ---------------------------------------------------------------- the generator's statistics by hand
def test_bh_and_cluster_test_by_hand():
    # sorted 0.01, 0.03, 0.04, 0.2 -> p*m/rank 0.04, 0.06, 0.0533, 0.2 -> running minimum from the top
    assert G.bh([0.01, 0.04, 0.03, 0.2]) == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.2])
    assert G.bh([]) == []
    rng = np.random.default_rng(2)
    y = rng.normal(0, 1, 4000)
    g = np.repeat(np.arange(200), 20)
    d = np.zeros(4000, bool)
    d[::5] = True
    assert G.cluster_p(y, d, g, 200) > 0.01                                       # no real difference
    y2 = y + np.where(d, 0.3, 0.0)
    assert G.cluster_p(y2, d, g, 200) < 1e-6
    # the clustering matters: a shared weekly shock makes a naive test far too sure, the clustered one is not
    shock = np.repeat(rng.normal(0, 3, 200), 20)
    dw = np.repeat(rng.random(200) < 0.5, 20)                                      # whole weeks in / out
    p_cl = G.cluster_p(y + shock, dw, g, 200)
    from scipy import stats
    p_naive = stats.ttest_ind((y + shock)[dw], (y + shock)[~dw]).pvalue
    assert p_cl > p_naive or p_cl > 0.05


def test_judge_marks_only_cells_that_pass_every_check():
    def c(p, d, w):
        return {"p": p, "d": d, "w": w, "_rest": [50, 50, 50]}
    good = c(0.0001, 0.12, [[40, 0.1], [40, 0.2], [40, 0.05]])
    flip = c(0.0001, 0.12, [[40, 0.1], [40, -0.02], [40, 0.05]])          # one window the other way
    thin = c(0.0001, 0.12, [[40, 0.1], [9, 0.2], [40, 0.05]])             # a window with 9 trades
    tiny = c(0.0001, 0.03, [[40, 0.02], [40, 0.04], [40, 0.03]])          # passes, but under 0.05 R
    weak = c(0.2, 0.3, [[40, 0.3], [40, 0.3], [40, 0.3]])                 # q > 5%
    worse = c(0.0001, -0.2, [[40, -0.1], [40, -0.3], [40, -0.2]])
    untested = {"d": 0.5, "w": [[5, 0.5]] * 3}
    scopes = {"A": {"rsi": [good, flip, thin, tiny, weak]}, "B": {"adx": [worse, untested]}}
    counts = G.judge(scopes)
    assert counts == {"tests": 6, "passed": 2, "better": 1, "worse": 1, "tiny": 1}
    assert good["ok"] == 1 and worse["ok"] == -1 and tiny.get("tiny") == 1
    assert all("ok" not in x for x in (flip, thin, tiny, weak, untested))
    assert weak["q"] == pytest.approx(0.2) and "q" not in untested


def test_committed_5_year_result_keeps_its_own_rules():
    d = IR.load_five()
    assert d is not None and d["version"] == 1 and d["label"] == "설명용, 판정 아님"
    r = d["rules"]
    assert r["fdr"] == 0.05 and r["min_effect_r"] == 0.05 and r["min_effect_added_after_first_run"] is True
    from paperbot.agents.roster3 import STRATEGY_KO
    assert set(d["strategies"]) == set(STRATEGY_KO) and d["tfs"] == ["15m", "30m", "1h", "4h"]
    assert d["trades"] == sum(d["per_tf"].values()) == d["pooled"]["n"]
    assert sum(v["n"] for v in d["strategies"].values()) == d["trades"]
    for k in IC.QUINT:
        for tf in d["tfs"]:
            e = d["edges"][k][tf]
            assert len(e) == 4 and e == sorted(e)
    marked, tested, tiny = [], 0, 0
    for name, v in [("", d["pooled"])] + list(d["strategies"].items()):
        n_ok = 0
        for k, row in v["cells"].items():
            assert len(row) == (5 if k in IC.QUINT else len(IC.FIXED[k]))
            for cell in row:
                tested += cell.get("p") is not None
                tiny += cell.get("tiny", 0)
                if cell.get("ok"):
                    n_ok += 1
                    marked.append(cell)
                    assert cell["q"] <= 0.05 and abs(cell["d"]) >= 0.05 and cell["ok"] == (1 if cell["d"] > 0 else -1)
                    for na, dw in cell["w"]:
                        assert na >= 10 and dw is not None and (dw > 0) == (cell["d"] > 0)
        if name:
            assert v["passed"] == n_ok
    assert len(marked) == r["passed"] and tested == r["tests"] and tiny == r["tiny"]
    assert r["better"] == sum(1 for x in marked if x["ok"] == 1)
    fv = IR.five_view()
    assert fv["ready"] and len(fv["marked"]) == r["passed"]
    ds = [abs(x["d"]) for x in fv["marked"]]
    assert ds == sorted(ds, reverse=True)
    assert IR.strategy_view("S2_ST_ROC")["cells"]["rsi"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        IR.strategy_view("NOT_A_STRATEGY")
    assert IR.five_view(os.path.join(ROOT, "nope.json"))["ready"] is False


# ---------------------------------------------------------------- paper-forward numbers
def test_paper_numbers_by_hand(tmp_path):
    """A hand-made 1h series: the paper part puts each trade in the range its own signal bar's numbers say."""
    five = IR.load_five()
    rng = np.random.default_rng(4)
    n = 700
    t = (kst(2026, 9, 1) // HOUR + np.arange(n)) * HOUR
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.r_[c[0], c[:-1]]
    bars = {"t": t, "o": o, "h": np.maximum(o, c) * 1.003, "l": np.minimum(o, c) * 0.997, "c": c,
            "v": rng.lognormal(3, 0.5, n)}
    ser = IC.series(bars["o"], bars["h"], bars["l"], bars["c"], bars["v"])
    rows = [{"signal_ts": int(t[i]) + HOUR - 1, "side": s} for i, s in ((650, 1), (660, -1))]
    rows.append({"signal_ts": int(t[-1]) + 5 * HOUR - 1, "side": 1})                 # a bar we do not have
    got = IR.numbers_at(rows, bars, "1h", five)
    assert got[2] is None
    for b, (i, s) in zip(got[:2], ((650, 1), (660, -1))):
        for k in IC.QUINT:
            want = IC.q_idx(IC.sided(k, np.array([ser[k][i]]), np.array([s])), five["edges"][k]["1h"])[0]
            assert b[k] == want


def test_paper_part_fills_from_market_db_and_waits_on_day_0(world, tmp_path):
    p = world["paper"]
    assert not p.get("waiting") and p["coverage"]["with_numbers"] >= IR.MIN_PAPER
    assert p["coverage"]["market_db"] == p["coverage"]["with_numbers"] and p["coverage"]["no_bars"] == 0
    assert sum(c["n"] for c in p["cells"]["rsi"]) == p["coverage"]["with_numbers"]
    assert sum(c["n"] for c in p["cells"]["session"]) == p["coverage"]["with_numbers"]
    assert all(set(c) >= {"n"} for row in p["cells"].values() for c in row)
    small = build_all(str(tmp_path / "d0"), days=1, hours=5)
    q = IR.paper_view(small["db"], small["now"], fake_frames())
    assert q["waiting"] and q["coverage"]["with_numbers"] < IR.MIN_PAPER
    # no market.db: the closed-bar fetcher is asked instead; neither: the trades count as no_bars, nothing guessed
    os.remove(os.path.join(str(tmp_path / "d0"), "market.db"))
    q2 = IR.paper_view(small["db"], small["now"], fake_frames())
    assert q2["coverage"]["frames"] == q2["coverage"]["with_numbers"] > 0
    q3 = IR.paper_view(small["db"], small["now"], None)
    assert q3["coverage"]["with_numbers"] == 0 and q3["coverage"]["no_bars"] == q3["coverage"]["trades"]
    assert IR.paper_view(str(tmp_path / "none.db"), small["now"])["error"] == "paper3.db 없음"


# ---------------------------------------------------------------- 강제청산 직후 by hand
def _liq_db(path, rows):
    from paperbot.liqstream import SCHEMA
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    for ts, sym, side, usd in rows:
        c.execute("INSERT INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ts, ts, sym, side, "LIMIT", "IOC", usd / 100, 100.0, 100.0, "FILLED", usd / 100, usd / 100, ts))
    c.commit()
    c.close()


def _liq_case(tmp_path):
    db = str(tmp_path / "paper3.db")
    st = blank(db, T0, [("S2_ST_ROC@15m", "strategy"), ("F01@15m", "ds200"), ("RANDOM_1@15m", "random")])
    rec0 = T0 + 2 * HOUR                                        # the recorder's first row
    # 100 quiet minutes of $10..$1,000 (the top 5% of minutes are bursts: the quiet $960-$1,000 ones, far from the
    # entries below) and, 100 minutes later, one large minute where longs were liquidated (SELL)
    rows = [(rec0 + k * MIN, "BTCUSDT", "BUY", 10.0 * (k + 1)) for k in range(100)]
    burst = rec0 + 200 * MIN
    rows += [(burst + 1000, "BTCUSDT", "SELL", 500_000.0), (burst + 2000, "BTCUSDT", "SELL", 400_000.0)]
    _liq_db(str(tmp_path / "liq.db"), rows)
    e1 = burst + 4 * MIN                                         # 3 minutes after the burst minute ended
    trade(st, "S2_ST_ROC@15m", e1, e1 + HOUR, 50.0, side=1)      # long after longs were liquidated: same
    trade(st, "S2_ST_ROC@15m", e1 + MIN, e1 + HOUR, -30.0, side=-1)   # short: opposite
    trade(st, "S2_ST_ROC@15m", burst + 21 * MIN, burst + 2 * HOUR, 20.0, side=1)   # 20 min after: only in 60
    trade(st, "S2_ST_ROC@15m", T0 + 30 * MIN, T0 + HOUR, 10.0, side=1)            # before the record: left out
    trade(st, "F01@15m", e1, e1 + HOUR, 70.0, side=1)
    trade(st, "RANDOM_1@15m", e1, e1 + HOUR, -5.0, side=-1)
    st.commit()
    st.close()
    return db, rec0


def test_liquidation_bursts_split_by_hand(tmp_path):
    db, rec0 = _liq_case(tmp_path)
    v = LE.view(db, T0 + DAY, "core")
    assert v["ready"] and v["first_ts"] == rec0 and v["trades"] == 4 and v["covered"] == 3 and v["waiting"]
    w = {x["minutes"]: x for x in v["per_window"]}
    assert w[5]["group"]["same"]["n"] == 1 and w[5]["group"]["opposite"]["n"] == 1 and w[5]["group"]["none"]["n"] == 1
    assert w[5]["group"]["same"]["wr"] == 1.0 and w[5]["group"]["opposite"]["wr"] == 0.0
    assert w[5]["group"]["same"]["mean_roe"] == pytest.approx(0.05) and w[5]["group"]["same"]["small"]
    assert w[15]["group"]["none"]["n"] == 1 and w[60]["group"]["same"]["n"] == 2 and w[60]["group"]["none"]["n"] == 0
    assert all(x["group"]["uncovered"] == 1 for x in v["per_window"])
    assert w[5]["coin_flips"]["opposite"]["n"] == 1                            # coin flips split the same way
    # 101 non-zero minutes: the 95th percentile is the 96th smallest ($960); bursts: $960-$1,000 and the big one
    assert v["coins"]["BTCUSDT"] == {"threshold_usd": 960.0, "minutes": 101, "bursts": 6}
    ds = LE.view(db, T0 + DAY, "ds200")
    assert ds["no_money"] and not (set(_keys(ds)) & DS_MONEY)
    assert {x["minutes"]: x for x in ds["per_window"]}[5]["group"]["same"] == {"n": 1, "wr": 1.0, "small": True}
    os.remove(str(tmp_path / "liq.db"))
    gone = LE.view(db, T0 + DAY, "core")
    assert gone["ready"] is False and "liq.db" in gone["why"]


def test_liquidations_need_30_minutes_on_record_before_a_burst_is_named(tmp_path):
    db = str(tmp_path / "paper3.db")
    st = blank(db, T0, [("S2_ST_ROC@15m", "strategy")])
    _liq_db(str(tmp_path / "liq.db"), [(T0 + k * MIN, "BTCUSDT", "SELL", 9e6 if k == 5 else 100.0) for k in range(10)])
    trade(st, "S2_ST_ROC@15m", T0 + 8 * MIN, T0 + HOUR, 5.0)
    st.commit()
    st.close()
    v = LE.view(db, T0 + DAY, "core")
    assert v["covered"] == 0 and v["per_window"][0]["group"]["uncovered"] == 1


# ---------------------------------------------------------------- 들고 있었다면 / 반대로 했다면 by hand
def test_mirror_pnl_by_hand():
    long_win = {"side": 1, "qty": 2.0, "entry_price": 100.0, "exit_price": 110.0, "fees": 1.5, "funding": 0.4,
                "margin": 50.0}
    assert K.mirror_pnl(long_win) == pytest.approx(-20.0 - 1.5 + 0.4)          # price reversed, fees again, funding back
    short_loss = {"side": -1, "qty": 1.0, "entry_price": 100.0, "exit_price": 104.0, "fees": 0.2, "funding": -0.1,
                  "margin": 10.0}
    assert K.mirror_pnl(short_loss) == pytest.approx(4.0 - 0.2 - 0.1)
    big = {**long_win, "exit_price": 200.0}                                     # the mirror would have been liquidated
    assert K.mirror_pnl(big) == -50.0
    assert K.mirror_pnl({"side": 1, "qty": None, "entry_price": 1, "exit_price": 2}) is None


def test_mirror_book_runs_one_account_per_real_account_and_stops_at_the_bust_line():
    def t(aid, k, pnl, eq_after, exit_price, qty=1.0, margin=100.0):
        return {"aid": aid, "entry": k, "exit": k + 1, "side": 1, "qty": qty, "entry_price": 100.0,
                "exit_price": exit_price, "fees": 0.0, "funding": 0.0, "margin": margin, "pnl": pnl, "eq_after": eq_after}
    # account A: +50 on 1,000 (mirror -50: 5% of its money), then the real account had 1,050 and lost 105
    # (10%): the mirror, now holding 950, wins 10% of 950 = 95
    a1, a2 = t("A", 0, 50.0, 1050.0, 150.0), t("A", 2, -105.0, 945.0, -5.0, qty=1.0, margin=500.0)
    book = K.mirror_book([a2, a1], 1000.0, 10.0)                                 # (any order in: by exit time)
    assert a1["mpnl"] == pytest.approx(-50.0) and a2["mpnl"] == pytest.approx(950 * 105 / 1050)
    assert book == {"accounts": 1, "busts": 0, "after_bust": 0}
    # account B: the mirror of a +1,000 trade loses its whole margin of 995 out of 1,000 -> 5 left, under the bust
    # line of 10: it takes no more trades
    b1, b2 = t("B", 0, 1000.0, 2000.0, 1100.0, margin=995.0), t("B", 2, -5.0, 1995.0, 95.0)
    book = K.mirror_book([b1, b2], 1000.0, 10.0)
    assert b1["mpnl"] == pytest.approx(-995.0) and b2["mpnl"] is None and book == {"accounts": 1, "busts": 1, "after_bust": 1}
    # never more than the account's money: a same-size sum would have said -1,500 out of 1,000
    c1 = t("C", 0, 1500.0, 2500.0, 1600.0, margin=2000.0)
    K.mirror_book([c1], 1000.0, 10.0)
    assert c1["mpnl"] == pytest.approx(-1000.0)
    assert t("D", 0, 1.0, None, 101.0).get("mpnl") is None and K.mirror_book([t("D", 0, 1.0, None, 101.0)], 1000.0)["busts"] == 0


def _market_db(path, sym_prices, t0, n):
    from paperbot.archive import SCHEMA
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    for sym, (p0, p1) in sym_prices.items():
        for k in range(n):
            px = p0 + (p1 - p0) * k / (n - 1)
            c.execute("INSERT INTO kline5m VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (sym, t0 + k * 300_000, px, px, px, px, 1.0, px, 1, 0.5, t0, "t"))
    c.commit()
    c.close()


def test_hold_and_mirror_by_hand(tmp_path):
    db = str(tmp_path / "paper3.db")
    st = blank(db, T0, [("S2_ST_ROC@15m", "strategy"), ("N17_KC_RSI@15m", "strategy"), ("RANDOM_1@15m", "random"),
                        ("F01@15m", "ds200")])
    trade(st, "S2_ST_ROC@15m", T0 + HOUR, T0 + 2 * HOUR, 100.0, side=1)
    trade(st, "N17_KC_RSI@15m", T0 + HOUR, T0 + 3 * HOUR, -40.0, side=-1)
    trade(st, "RANDOM_1@15m", T0 + HOUR, T0 + 2 * HOUR, 25.0, side=1)
    trade(st, "F01@15m", T0 + HOUR, T0 + 2 * HOUR, 60.0, side=1)
    st.commit()
    st.close()
    now = T0 + 6 * HOUR
    prices = {s: (100.0, 110.0) for s in HC.SYMBOLS}
    prices["ETHUSDT"] = (100.0, 90.0)
    _market_db(str(tmp_path / "market.db"), prices, T0, 72)                      # 6 hours of 5-minute bars
    v = HC.view(db, now, "core", None)
    assert v["accounts"] == 2 and v["flip_accounts"] == 1 and v["initial"] == 5000.0
    assert v["mine"]["ret"] == pytest.approx(60.0 / 10_000) and v["mine"]["wr"] == 0.5
    assert v["coin_flips"]["ret"] == pytest.approx(25.0 / 5000)
    eth = [c for c in v["hold"]["coins"] if c["symbol"] == "ETHUSDT"][0]
    assert eth["chg"] == pytest.approx(-0.1) and eth["source"] == "market_db"
    assert v["hold"]["basket_chg"] == pytest.approx((5 * 0.1 - 0.1) / 6, abs=1e-5)
    assert v["hold_curve"]["basket"][0] == 0.0 and v["hold_curve"]["basket"][-1] == pytest.approx((5 * 0.1 - 0.1) / 6, abs=1e-5)
    assert v["curve"]["group"][-1] == pytest.approx(v["mine"]["ret"], abs=1e-5) and v["curve"]["group"][0] == 0.0
    assert v["waiting"] and v["mine"]["mirror"]["trades"] == 2
    # anasyn_world.trade: entry = exit price, so the mirror pays the fees again and nothing else
    assert v["mine"]["mirror"]["mirror_ret"] == pytest.approx(-0.2 / 10_000)
    reel = HC.view(db, now, "reel", None)                                       # no closed trade: no 0%, no flat line
    assert reel["mine"]["trades"] == 0 and reel["mine"]["ret"] is None and reel["mine"]["mirror"]["mirror_ret"] is None
    assert all(x is None for x in reel["curve"]["group"] + reel["curve"]["mirror"] + reel["curve"]["flips"])
    assert reel["hold_curve"]["basket"][-1] is not None                         # the coins' prices are still there
    ds = HC.view(db, now, "ds200", None)
    assert ds["no_money"] and not (set(_keys(ds)) & DS_MONEY)
    assert ds["mine"]["wr"] == 1.0 and ds["hold"]["basket_chg"] == pytest.approx(v["hold"]["basket_chg"])
    os.remove(str(tmp_path / "market.db"))                                      # 1-hour closed bars instead
    f = HC.view(db, now, "core", fake_frames())
    assert f["hold"]["price_source"] == ["frames"] and f["hold"]["known"] == 6
    none = HC.view(db, now, "core", None)
    assert none["hold"]["known"] == 0 and none["hold"]["basket_chg"] is None


# ---------------------------------------------------------------- GH Coin과 같은 방향 by hand
def _gh(folder, calls):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "calls.jsonl"), "w") as fh:
        for cid, sym, side, t, end in calls:
            fh.write(json.dumps({"ev": "open", "id": cid, "sym": sym, "side": side, "t": t}) + "\n")
            fh.write(json.dumps({"ev": "open", "id": cid + "-m", "of": cid, "mirror": True, "sym": sym, "side": -side,
                                 "t": t}) + "\n")
            if end:
                fh.write(json.dumps({"ev": "close", "id": cid, "sym": sym, "side": side, "t": t, "end": end}) + "\n")


def test_gh_coin_same_opposite_none_by_hand(tmp_path):
    db = str(tmp_path / "paper3.db")
    st = blank(db, T0, [("S2_ST_ROC@15m", "strategy"), ("F01@15m", "ds200"), ("RANDOM_1@15m", "random")])
    c1 = T0 + HOUR
    _gh(str(tmp_path / "ghcoin"), [("a", "BTCUSDT", 1, c1, c1 + 2 * HOUR), ("b", "ETHUSDT", -1, c1, None)])
    trade(st, "S2_ST_ROC@15m", c1 + HOUR, c1 + 2 * HOUR, 30.0, side=1)                     # same (still open)
    trade(st, "S2_ST_ROC@15m", c1 + 3 * HOUR, c1 + 4 * HOUR, -10.0, side=-1)               # opposite (closed by then)
    trade(st, "S2_ST_ROC@15m", c1 + 25 * HOUR, c1 + 26 * HOUR, 5.0, side=1)                # more than 24 h: none
    trade(st, "S2_ST_ROC@15m", c1 + HOUR, c1 + 2 * HOUR, 8.0, symbol="ETHUSDT", side=-1)   # same (short)
    trade(st, "S2_ST_ROC@15m", T0 + 10 * MIN, T0 + HOUR, 1.0, side=1)                      # before the record
    trade(st, "S2_ST_ROC@15m", c1 + HOUR, c1 + 2 * HOUR, 2.0, symbol="SOLUSDT", side=1)    # no call on SOL
    trade(st, "F01@15m", c1 + HOUR, c1 + 2 * HOUR, 9.0, side=-1)
    trade(st, "RANDOM_1@15m", c1 + HOUR, c1 + 2 * HOUR, -3.0, side=1)
    st.commit()
    st.close()
    v = GA.view(db, T0 + 3 * DAY, "core")
    m = v["mine"]
    assert v["group"] == "core" and v["calls"] == 2 and v["first_ts"] == c1 and v["waiting"]
    assert (m["same"]["n"], m["opposite"]["n"], m["none"]["n"], m["before"]) == (2, 1, 2, 1)
    assert m["open_at_entry"] == 2 and m["same"]["mean_roe"] == pytest.approx((0.03 + 0.008) / 2)
    assert v["coin_flips"]["same"]["n"] == 1 and v["with_call"] == 3
    ds = GA.view(db, T0 + 3 * DAY, "ds200")
    assert ds["no_money"] and not (set(_keys(ds)) & DS_MONEY) and ds["mine"]["opposite"] == {"n": 1, "wr": 1.0, "small": True}
    # a call made at the entry's own bar close is written after the entry: it does not count (strictly before)
    gh = GA.calls(str(tmp_path / "ghcoin"))
    assert GA.latest(gh, "BTCUSDT", c1)[0] == "none" and GA.latest(gh, "BTCUSDT", c1 + 1)[0] == "long"
    shutil.rmtree(str(tmp_path / "ghcoin"))
    assert GA.view(db, T0 + 3 * DAY, "core")["ready"] is False


# ---------------------------------------------------------------- the world: shapes, waiting, read-only
def test_world_views_shapes_and_deepseek(world):
    for g in ("core", "reel"):
        assert not world["liq"][g].get("no_money") and world["hold"][g]["mine"]["ret"] is not None
    for name in ("liq", "hold", "gh"):
        ds = world[name]["ds200"]
        assert ds["no_money"] and not (set(_keys(ds)) & DS_MONEY), name
    c = world["liq"]["core"]
    assert not c.get("waiting") and [x["minutes"] for x in c["per_window"]] == [5, 15, 60]
    for x in c["per_window"]:
        g = x["group"]
        assert g["same"]["n"] + g["opposite"]["n"] + g["none"]["n"] + g["uncovered"] == c["trades"]
    h = world["hold"]["core"]
    assert len(h["curve"]["t"]) == len(h["curve"]["group"]) == len(h["hold_curve"]["basket"]) <= HC.MAX_POINTS + 1
    assert h["hold"]["known"] == 6
    gh = world["gh"]["core"]
    assert gh["mine"]["same"]["n"] + gh["mine"]["opposite"]["n"] + gh["mine"]["none"]["n"] + gh["mine"]["before"] == gh["trades"]


def test_views_never_write_a_database(tmp_path):
    info = build_all(str(tmp_path), days=3, hours=10)
    files = [os.path.join(str(tmp_path), f) for f in ("paper3.db", "liq.db", "market.db",
                                                       os.path.join("ghcoin", "calls.jsonl"))]
    before = {f: _sha(f) for f in files}
    listing = sorted(os.listdir(str(tmp_path)))
    IR.paper_view(info["db"], info["now"], fake_frames())
    for g in ("core", "ds200", "reel"):
        LE.view(info["db"], info["now"], g)
        HC.view(info["db"], info["now"], g, fake_frames())
        GA.view(info["db"], info["now"], g)
    assert {f: _sha(f) for f in files} == before
    # opening a WAL database read-only lets SQLite itself add its empty side files; nothing else appears
    new = sorted(set(os.listdir(str(tmp_path))) - set(listing))
    assert all(re.fullmatch(r"\w+\.db-(wal|shm)", n) and n.split("-")[0] in listing for n in new), new
    assert all(os.path.getsize(os.path.join(str(tmp_path), n)) == 0 for n in new if n.endswith("-wal"))


def test_routes_are_registered_and_answer(world):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    for m in ("indranges", "liqentry", "holdcmp", "ghagree"):
        assert m in MORE.MODULES
    app = fastapi.FastAPI()
    done = MORE.register_all(app, data=None, rooms=None, db=world["db"], daily_db=None, agents_db=None,
                             checkpoint_db=None, candles=None, frames=fake_frames())
    assert done["indranges"]["routes"] == ["/api/v4/indranges", "/api/v4/indranges/strategy", "/api/v4/indranges/paper"]
    c = TestClient(app)

    def got(path):
        for _ in range(40):
            x = c.get(path).json()
            if not x.get("pending"):
                return x
            assert x["note"]
        raise AssertionError(path)
    assert got("/api/v4/indranges")["ready"] and got("/api/v4/indranges/strategy?name=V45_AMB")["name"] == "V45_AMB"
    assert c.get("/api/v4/indranges/strategy?name=x").status_code == 404
    assert "cells" in got("/api/v4/indranges/paper")
    assert got("/api/v4/liqentry")["group"] == "core" and got("/api/v4/liqentry?group=ds200")["no_money"]
    assert got("/api/v4/holdcmp?group=reel")["group"] == "reel" and got("/api/v4/ghagree")["calls"] > 0
    for p in ("/api/v4/liqentry", "/api/v4/holdcmp", "/api/v4/ghagree"):
        assert c.get(p + "?group=flip").status_code == 400                     # never silently the 36


def test_routes_share_the_dashboards_worker(tmp_path):
    pytest.importorskip("fastapi")
    from paperbot.dash.app import create_app
    db = str(tmp_path / "paper3.db")
    blank(db, T0, [("S2_ST_ROC@15m", "strategy")]).close()
    app = create_app(db, None, b"s" * 32)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/api/v4/indranges", "/api/v4/indranges/paper", "/api/v4/indranges/strategy", "/api/v4/liqentry",
            "/api/v4/holdcmp", "/api/v4/ghagree"} <= paths


# ---------------------------------------------------------------- the page (node, tiny DOM)
def _render(module: str, fn: str, data: dict, group: str = "core", extra: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + SCREENS
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              f"const M = await import('{base}/{module}');\n"
              f"const d = {json.dumps(data)}; const extra = {json.dumps(extra or {})};\n"
              "const api = (p) => Promise.resolve(Object.entries(extra).find(([k]) => p.startsWith(k))?.[1] || {});\n"
              f"const env = {{verdictTs: null, group: '{group}', track() {{}}, "
              "ctx: {href: () => '#', alive: () => true, api, timeout: () => 0}};\n"
              f"const nodes = M.{fn}(d, env);\n"
              "await new Promise((r) => setTimeout(r, 30));\n"
              "console.log(JSON.stringify(D.walk(nodes)));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_indranges_page_words(world):
    five = IR.five_view()
    strat = IR.strategy_view(max(five["strategies"], key=lambda s: five["strategies"][s]["passed"]))
    out = _render("analysis-indr.js", "indranges", five, extra={"/api/v4/indranges/strategy": strat,
                                                                 "/api/v4/indranges/paper": world["paper"]})
    t = out["text"]
    for w in ("들어갈 때 어떤 숫자 구간에서 결과가 좋았나", "설명용, 판정 아님", "과적합", "잠긴 규칙은 이 화면 때문에 바뀌지 않습니다",
              "기존 36 합쳐서", "매매법별", "표시된 칸 모두", "지금 실험", "어떻게 계산했나", "차이 없음", "더 좋음", "첫 실행 뒤에 더한 규칙"):
        assert w in t, w
    assert "채워지는 중" not in t and "5년" in t
    wait = _render("analysis-indr.js", "indranges", five, extra={"/api/v4/indranges/strategy": strat,
                                                                  "/api/v4/indranges/paper": {"waiting": True, "min_trades": 100,
                                                                                              "coverage": {"with_numbers": 7, "trades": 9}}})
    assert "채워지는 중" in wait["text"] and "기존 36 끝난 거래 100건 필요" in wait["text"] and "지금 7건" in wait["text"]
    missing = _render("analysis-indr.js", "indranges", {"ready": False, "why": "5년 결과 파일이 없습니다"})
    assert "5년 결과 파일이 없습니다" in missing["text"]


def test_liqentry_page_words(world):
    t = _render("analysis-liqent.js", "liqentry", world["liq"]["core"])["text"]
    for w in ("기록 시작:", "청산당한 쪽과 같은 방향", "청산당한 쪽과 반대 방향", "그 밖의 진입", "동전 봇 (참고)", "평균 ROE", "참고",
              "코인별 기준", "설명용, 판정 아님"):
        assert w in t, w
    ds = _render("analysis-liqent.js", "liqentry", world["liq"]["ds200"], "ds200")["text"]
    assert "돈 숫자 없음" in ds and "ROE" not in ds.replace("ROE = ", "") and "USDT" not in ds
    wait = _render("analysis-liqent.js", "liqentry", {"group": "core", "ready": True, "first_ts": T0, "trades": 9, "covered": 4,
                                                       "min_covered": 20, "waiting": True})["text"]
    assert "채워지는 중" in wait and "진입 20건 필요" in wait and "직후 진입 vs 그 밖" not in wait
    off = _render("analysis-liqent.js", "liqentry", {"group": "core", "ready": False, "why": "liq.db 없음"})["text"]
    assert "liq.db 없음" in off


def test_hold_page_words(world):
    out = _render("analysis-hold.js", "holdcmp", world["hold"]["core"])
    t = out["text"]
    for w in ("그냥 들고 있기", "반대로 했다면", "대충 계산", "손절·익절 자리가 달라서", "수수료는 거꾸로 한 거래도", "1배", "동전 봇 (참고)",
              "모의 · 실제 시세", "코인별 그냥 들고 있기", "곡선"):
        assert w in t, w
    assert any("a7-l-mir" in c for c in out["classes"]) or "곡선은 점이 3개 이상" in t
    ds = _render("analysis-hold.js", "holdcmp", world["hold"]["ds200"], "ds200")["text"]
    assert "돈 숫자 없음" in ds and "수익률은 딥시크 화면에서" in ds and "모의 · 실제 시세" not in ds
    assert "코인 6개 그냥 들고 있기" in ds                                    # the coins' prices stay (market data)


def test_ghagree_page_words(world):
    t = _render("analysis-ghagree.js", "ghagree", world["gh"]["core"])["text"]
    for w in ("GH Coin과 같은 방향", "GH Coin과 반대 방향", "GH Coin 타점 없음", "24시간", "동전 봇 (참고)", "GH Coin 타점 수",
              "분석 › GH Coin", "매매를 바꾸지 않습니다"):
        assert w in t, w
    ds = _render("analysis-ghagree.js", "ghagree", world["gh"]["ds200"], "ds200")["text"]
    assert "돈 숫자 없음" in ds and "평균 ROE" not in ds
    off = _render("analysis-ghagree.js", "ghagree", {"group": "core", "ready": False, "why": "GH Coin 타점 기록이 아직 없습니다"})["text"]
    assert "GH Coin 타점 기록이 아직 없습니다" in off


def test_wiring_features_tokens_and_honesty_words():
    a = _read("analysis.js")
    for line in ('{id: "indranges", label: "좋은 수치 찾기", path: "/api/v4/indranges", render: indranges, groups: "core"',
                 '{id: "liqentry", label: "강제청산 직후", path: "/api/v4/liqentry", render: liqentry, groups: "groups", feature: "liq"',
                 '{id: "hold", label: "들고 있었다면", path: "/api/v4/holdcmp", render: holdcmp, groups: "groups"',
                 '{id: "ghagree", label: "GH Coin 방향", path: "/api/v4/ghagree", render: ghagree, feature: "ghcoin", groups: "groups"'):
        assert line in a, line
    assert a.index('{id: "ghcoin"') < a.index('{id: "ghagree"')                 # next to the GH Coin tab
    assert '@import url("analysis-ana7a.css");' in _read("analysis.css")
    for f in ("analysis-a7kit.js", "analysis-indr.js", "analysis-liqent.js", "analysis-hold.js", "analysis-ghagree.js"):
        src = _read(f)
        assert "innerHTML" not in src and "toLocaleString" not in src and "localStorage" not in src, f
        assert not re.search(r"합격(?!·불합격)|통과|추천|하세요|사세요|파세요", src), f
    css = _read("analysis-ana7a.css")
    for m in re.finditer(r"font-size:\s*([^;}]+)", css):
        assert m.group(1).strip().startswith("var(--t-"), m.group(0)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    inv = open(os.path.join(V4, "INVENTORY.md"), encoding="utf-8").read()
    for p in ("/api/v4/indranges", "/api/v4/liqentry", "/api/v4/holdcmp", "/api/v4/ghagree"):
        assert p in inv
