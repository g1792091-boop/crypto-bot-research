"""Paper v4 checkpoint verdict (paperbot/checkpoint.py; docs/paper-v4-verdict.md): the alpha-split FDR families
(owners' D5 (b)), the fair coin-flip null (D7: long share, coin set, ET-session bar mask, the reel's own exits), the
zero-rate and coverage holds (M9, M10), the per-group Q5 warnings (D8, M12) and the reel's bots against ReelEngine."""

import datetime as dt
import json

import numpy as np
import pytest

from paperbot import Bar, Signal
from paperbot import checkpoint as ck
from paperbot.config import V3_SYMBOLS, V4_GROUP_JUDGED, v3_settings
from paperbot.reel_engine import BB_LEN, ReelEngine
from test_checkpoint import (BR, DAY, MIN, S, SPECS, T0, _LenientCells, _acct, _minutes_for, _paper_db, _snap,
                             _trades, synth_minutes)

FIVE = 5 * MIN


@pytest.fixture(autouse=True)
def _made_up_cells(monkeypatch):
    monkeypatch.setattr(ck, "_P_BEST_CELLS", _LenientCells(ck.p_best_cells()))


# ---------------------------------------------------------------------------- families (D5)
def test_n_bots_and_alpha_split_resolve_one_perfect_account_in_every_family():
    """m = 241 judged accounts (108 core + 132 DeepSeek + 1 reel): with 10,000 bots, one account that beats every
    bot (p = 1/10,001) passes in each family, the others being uniform nulls."""
    assert ck.N_BOTS == 10_000 and ck.REHEARSAL_BOTS == 2_000
    assert V4_GROUP_JUDGED["core"] == 108 and V4_GROUP_JUDGED["ds200"] == 132 and V4_GROUP_JUDGED["reel"] == 1
    for g, a in ck.FAMILY_ALPHA.items():
        assert 1 / (ck.N_BOTS + 1) <= a / V4_GROUP_JUDGED[g]          # the resolution the family needs
    assert 1 / (ck.REHEARSAL_BOTS + 1) > ck.FAMILY_ALPHA["ds200"] / V4_GROUP_JUDGED["ds200"]   # the rehearsal cannot
    cp = T0 + 30 * DAY
    accts, p = {}, {}
    rng = np.random.default_rng(3)
    for g, kind, n, tf in (("core", "strategy", 108, "1h"), ("ds200", "ds200", 132, "1h"), ("reel", "reel", 1, "5m")):
        for k in range(n):
            aid = f"{g}{k}@{tf}"
            accts[aid] = {**_acct(tf, 40, 9000.0, T0, cp, kind=kind), "strategy": f"{g}{k}"}
            p[aid] = 1 / (ck.N_BOTS + 1) if k == 0 else float(rng.uniform(0.05, 1.0))
    s = _snap(cp, accts)
    rows, tasks = ck.plan(s, {}, {}, S)
    assert len(tasks) == 241 and {t.group for t in tasks} == {"core", "ds200", "reel"}
    summ = ck.decide(s, rows, tasks, {a: {"p": v} for a, v in p.items()})
    assert summ["tested"] == 241 and summ["luck_passed"] == 3
    for g, tf in (("core", "1h"), ("ds200", "1h"), ("reel", "5m")):
        assert rows[f"{g}0@{tf}"]["status"] == ck.PASS1 and rows[f"{g}0@{tf}"]["luck_pass"]
    assert [f["luck_passed"] for f in summ["families"]] == [1, 1, 1]
    # one BH family at 0.10 over all 241 with 2,000 bots could not resolve it: 1/2,001 > 0.10 / 241
    assert not ck.bh([1 / 2001] + [0.5] * 240, 0.10)[1][0]


def test_reel_task_is_5m_and_ds_4h_observation_only():
    cp = T0 + 30 * DAY
    accts = {"REEL_H1@5m": {**_acct("5m", 40, 9000.0, T0, cp, kind="reel"), "strategy": "REEL_H1"},
             "F3_BOS@4h": {**_acct("4h", 40, 9000.0, T0, cp, kind="ds200"), "strategy": "F3_BOS"},
             "F3_BOS@15m": {**_acct("15m", 40, 9000.0, T0, cp, kind="ds200"), "strategy": "F3_BOS"},
             "RANDOM_1@5m": {**_acct("5m", 40, 9000.0, T0, cp, kind="random"), "strategy": "RANDOM_1"}}
    rows, tasks = ck.plan(_snap(cp, accts), {}, {}, S)
    t = {x.aid: x for x in tasks}
    assert set(t) == {"REEL_H1@5m", "F3_BOS@15m"}
    assert (t["REEL_H1@5m"].tf, t["REEL_H1@5m"].group, t["REEL_H1@5m"].exits) == ("5m", "reel", "reel")
    assert t["REEL_H1@5m"].long_share == 1.0 and t["REEL_H1@5m"].p_best == 0.0
    assert t["F3_BOS@15m"].p_best == 0.0 and t["F3_BOS@15m"].group == "ds200"
    assert rows["F3_BOS@4h"]["status"] == ck.OBSERVE and "4시간" in rows["F3_BOS@4h"]["reason"]
    assert rows["RANDOM_1@5m"]["status"] == ck.OBSERVE
    # the reel's rate: its own signals per (6 coins x 5m bars)
    bars = (cp - (T0 + 3_600_000)) // FIVE
    assert rows["REEL_H1@5m"]["rate"] == pytest.approx(400 / (6 * bars), rel=0.01)


@pytest.mark.parametrize("tf", ["15m", "1h"])
def test_originals_byte_identical_with_or_without_the_ds_and_reel_tasks(tf):
    cp = T0 + 30 * DAY
    lo = T0 + 20 * DAY
    core = {f"C{k}@{tf}": _acct(tf, 40, 5000.0 + 300 * k, lo, cp, created=lo) for k in range(3)}
    others = {"F9_FVG@" + tf: {**_acct(tf, 40, 5600.0, lo, cp, created=lo, kind="ds200"), "strategy": "F9_FVG"},
              "F14_SMT@" + tf: {**_acct(tf, 40, 5400.0, lo, cp, created=lo, kind="ds200"), "strategy": "F14_SMT"},
              "REEL_H1@5m": {**_acct("5m", 40, 5200.0, lo, cp, created=lo, kind="reel"), "strategy": "REEL_H1"}}
    m = synth_minutes(lo - 4 * DAY, cp, seed=9)
    old_period = ck.PERIOD_DAYS
    ck.PERIOD_DAYS = 10
    try:
        res = []
        for accts in (core, {**core, **others}):
            s = _snap(cp, accts)
            rows, tasks = ck.plan(s, {}, {}, S)
            pv, groups = ck.run_tasks(tasks, lambda a, b: m.window(a, b), S, BR, SPECS, 40, 7, 5000.0)
            ck.decide(s, rows, tasks, pv)
            res.append((pv, groups, rows))
    finally:
        ck.PERIOD_DAYS = old_period
    (pv0, g0, r0), (pv1, g1, r1) = res
    for aid in core:
        assert pv1[aid] == pv0[aid] and r1[aid]["q"] == r0[aid]["q"]
    assert g1[0] == {**g0[0], "seconds": g1[0]["seconds"]}
    fams = [g.get("group", "core") for g in g1]
    assert fams == ["core", "ds200", "reel"] and g1[2]["exits"] == "reel" and g1[2]["timeframe"] == "5m"
    assert g1[1]["seed"] == g0[0]["seed"] + [ck.FAMILY_SALT["ds200"]]


# ---------------------------------------------------------------------------- the fair null (D7)
def test_long_share_draws_only_longs_and_keeps_the_stream():
    idx = np.arange(500)
    rates = np.full(500, 0.5)
    f1, s1 = ck.random_draws(np.random.default_rng(4), 1.0)(0, idx, rates, 6)
    f0, s0 = ck.random_draws(np.random.default_rng(4))(0, idx, rates, 6)
    assert (s1 == 1).all() and (f1 == f0).all() and (s0 == -1).any()
    fh, sh = ck.random_draws(np.random.default_rng(4), 0.5)(0, idx, rates, 6)
    assert (sh == s0).all() and (fh == f0).all()                         # 0.5 is exactly the v3 draw
    per = np.where(idx < 250, 1.0, 0.0)
    _, sp = ck.random_draws(np.random.default_rng(4), per)(0, idx, rates, 6)
    assert (sp[:250] == 1).all() and (sp[250:] == -1).all()


def _spy_sizes(monkeypatch):
    seen = []
    real = ck.size_vec
    state = {"ts": None}

    def spy(s, eq, side, fill, *a, **kw):
        seen.append((state["ts"], np.asarray(side, float).copy(), np.asarray(fill, float).copy()))
        return real(s, eq, side, fill, *a, **kw)
    monkeypatch.setattr(ck, "size_vec", spy)
    return seen, state


def test_coin_mask_long_share_and_session_mask_reach_the_entries(monkeypatch):
    lo = T0 + 4 * DAY
    hi = lo + 2 * DAY
    m = synth_minutes(T0, hi, seed=5)
    atr = ck.tf_atr(m, "15m")
    seen, state = _spy_sizes(monkeypatch)
    N = 60
    no_btc = np.array([x != "BTCUSDT" for x in V3_SYMBOLS])
    ck.simulate_bots(m, "15m", lo, hi, np.full(N, 0.05), S, BR, SPECS, seed=[1], atr=atr, long_share=1.0,
                     coin_mask=no_btc)
    assert seen and all((sd == 1).all() for _, sd, _ in seen)
    btc_px = (np.nanmin(m.l[:, 0]), np.nanmax(m.h[:, 0]))
    assert not any(((f >= btc_px[0] * 0.98) & (f <= btc_px[1] * 1.02)).any() for _, _, f in seen)   # no BTC entry
    # session mask: entries only on bars the definition can fire on (F15_LON_BRK: bar open 05:00-12:00 ET)
    seen.clear()

    def bar_mask(ts, idx):
        state["ts"] = ts
        return np.full(len(idx), bool(ck.session_mask("F15_LON_BRK", "15m", [ts])[0]))
    ck.simulate_bots(m, "15m", lo, hi, np.full(N, 0.05), S, BR, SPECS, seed=[1], atr=atr, bar_mask=bar_mask)
    assert seen and all(ck.session_mask("F15_LON_BRK", "15m", [ts])[0] for ts, _, _ in seen)
    assert {300 <= ck.et_minute(ts - 15 * MIN) < 720 for ts, _, _ in seen} == {True}


def test_et_clock_follows_us_dst_like_zoneinfo():
    zoneinfo = pytest.importorskip("zoneinfo")
    ny = zoneinfo.ZoneInfo("America/New_York")
    start = int(dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc).timestamp() * 1000)
    for t in range(start, start + 14 * DAY, 15 * MIN):          # across the US DST end on 2026-11-01
        w = dt.datetime.fromtimestamp(t / 1000, ny)
        assert ck.et_minute(t) == w.hour * 60 + w.minute, t
    for y, m_, d_ in ((2026, 3, 8), (2027, 3, 14)):              # DST start: second Sunday of March, 07:00 UTC
        t = int(dt.datetime(y, m_, d_, 7, tzinfo=dt.timezone.utc).timestamp() * 1000)
        assert ck.et_offset_minutes(t - 1) == -300 and ck.et_offset_minutes(t) == -240


@pytest.mark.parametrize("tf,open_min", [("15m", 615), ("30m", 600), ("1h", 600)])
def test_session_judge_bar_of_the_us_open(tf, open_min):
    """F15_OPEN0930: judged on the first bar at or after the one holding 09:30 ET whose close is at or after 10:30."""
    span = ck.TF_MS[tf]
    day = int(dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc).timestamp() * 1000)
    closes = day + np.arange(1, DAY // span + 1) * span
    ok = ck.session_mask("F15_OPEN0930", tf, closes)
    assert ok.sum() == 1 and ck.et_minute(int(closes[ok][0]) - span) == open_min
    assert ck.session_mask("F3_BOS", tf, closes).all()
    zero = ck.session_mask("F15_OPEN0000", tf, closes)
    assert ck.et_minute(int(closes[zero][0]) - span) == {"15m": 45, "30m": 30, "1h": 0}[tf]


def test_session_masks_cover_every_lib_c_session_signal():
    """The pre-registered masks hold every bar lib_c's F15 definitions fire on (synthetic bars across the DST end;
    lib_c loaded in a subprocess so sys.path and the warnings filters stay clean)."""
    import subprocess
    import sys
    code = r'''
import json, sys, importlib.util, numpy as np, pandas as pd
spec = importlib.util.spec_from_file_location("lib_c", "research/deepseek200/lib_c.py")
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
out = {}
rng = np.random.default_rng(1)
for tfm in (15, 30, 60):
    n = 40 * 1440 // tfm
    ts = pd.date_range("2026-10-10", periods=n, freq=f"{tfm}min").to_numpy()
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[100, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    sig = L.session_signals(ts, o, h, l, c, tfm)
    opens = (ts.astype("datetime64[ms]").astype(np.int64)).tolist()
    out[str(tfm)] = {k: [opens[i] for i in np.flatnonzero(v[0] | v[1])] for k, v in sig.items()}
print(json.dumps(out))
'''
    import os
    root = os.path.join(os.path.dirname(__file__), "..")
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        pytest.skip(f"lib_c not loadable here: {r.stderr[-300:]}")
    got = json.loads(r.stdout.strip().splitlines()[-1])
    n_fired = 0
    for tfm, defs in got.items():
        tf = {"15": "15m", "30": "30m", "60": "1h"}[tfm]
        span = ck.TF_MS[tf]
        assert set(defs) == set(ck.SESSION_RULES)
        for name, opens in defs.items():
            n_fired += len(opens)
            if opens:
                assert ck.session_mask(name, tf, np.asarray(opens, np.int64) + span).all(), (tf, name)
    assert n_fired > 100


def test_ds_bots_get_coin_set_and_session_from_the_definition():
    cp = T0 + 30 * DAY
    accts = {"F14_SMT@15m": {**_acct("15m", 40, 9000.0, T0, cp, kind="ds200"), "strategy": "F14_SMT"},
             "F15_LON_BRK@15m": {**_acct("15m", 40, 9000.0, T0, cp, kind="ds200"), "strategy": "F15_LON_BRK"},
             "F15_ORB@15m": {**_acct("15m", 40, 9000.0, T0, cp, kind="ds200"), "strategy": "F15_ORB"}}
    for a in accts.values():
        a["signals_long"] = {d: n // 4 for d, n in a["signals"].items()}
    rows, tasks = ck.plan(_snap(cp, accts), {}, {}, S)
    t = {x.aid: x for x in tasks}
    assert "BTCUSDT" not in t["F14_SMT@15m"].coins and len(t["F14_SMT@15m"].coins) == 5
    assert t["F15_LON_BRK@15m"].session == "F15_LON_BRK" and t["F15_ORB@15m"].session is None
    assert all(x.long_share == pytest.approx(0.25) for x in tasks)
    n = 400
    lo = T0 + 3_600_000
    assert rows["F14_SMT@15m"]["rate"] == pytest.approx(ck.signal_rate(n, "15m", lo, cp, coins=5))
    masked = ck.signal_rate(n, "15m", lo, cp, session="F15_LON_BRK")
    assert masked == pytest.approx(rows["F15_LON_BRK@15m"]["rate"]) and masked > 2.5 * ck.signal_rate(n, "15m", lo, cp)
    kw = ck._pass_rules(tasks, 3, "15m", V3_SYMBOLS)
    assert kw["coin_mask"].shape == (9, 6) and not kw["coin_mask"][:3, 0].any() and kw["coin_mask"][3:].all()
    assert (kw["long_share"] == 0.25).all() and "exits" not in kw


# ---------------------------------------------------------------------------- holds and warnings (M3, M9, M10, M12)
def test_missing_core_cell_stops_the_verdict(monkeypatch):
    monkeypatch.setattr(ck, "_P_BEST_CELLS", None)               # the real cells file
    cp = T0 + 30 * DAY
    with pytest.raises(ck.MissingCell):
        ck.plan(_snap(cp, {"NOPE@1h": {**_acct("1h", 40, 9000.0, T0, cp), "strategy": "NOPE"}}), {}, {}, S)
    rows, tasks = ck.plan(_snap(cp, {"N02_ST_KST@1h": {**_acct("1h", 40, 9000.0, T0, cp), "strategy": "N02_ST_KST"},
                                     "F9_OB@1h": {**_acct("1h", 40, 9000.0, T0, cp, kind="ds200"), "strategy": "F9_OB"}}),
                          {}, {}, S)
    p = {t.aid: t.p_best for t in tasks}
    assert p["N02_ST_KST@1h"] == ck.p_best_cells()["N02_ST_KST|1h"]["p_best"] > 0 and p["F9_OB@1h"] == 0.0


def test_signals_logged_under_another_key_hold_not_pass(tmp_path):
    cp = T0 + 30 * DAY
    lo = T0 + 5 * 3_600_000
    path = str(tmp_path / "paper3.db")
    _paper_db(path, {"F3_BOS@1h": {"kind": "ds200", "wallet": 400_000.0, "trades": _trades(40, lo, cp, 9875.0),
                                   "signals": 0},
                     "F3_BOS_X@1h": {"kind": "ds200", "wallet": 5000.0, "trades": [], "signals": 400}}, cp)
    v = ck.run_due(path, str(tmp_path / "c.db"), _minutes_for(), S, BR, SPECS, None, now_ms=cp + 1, n_bots=50,
                   log=lambda *_: None)[0]
    r = v["accounts"]["F3_BOS@1h"]
    assert r["status"] == ck.HOLD and "신호 기록 0건" in r["reason"] and r["group"] == "ds200"
    assert v["tested"] == 0 and any("신호 기록 0건" in w and "딥시크만 해당" in w for w in v["warnings"])


def test_account_missing_from_the_day_state_is_held_and_warned(tmp_path):
    import sqlite3
    cp = T0 + 30 * DAY
    lo = T0 + 5 * 3_600_000
    path = str(tmp_path / "paper3.db")
    _paper_db(path, {"GOOD@1h": {"wallet": 400_000.0, "trades": _trades(40, lo, cp, 9875.0), "signals": 400},
                     "REEL_H1@5m": {"kind": "reel", "wallet": 9000.0, "trades": _trades(40, lo, cp, 100.0),
                                    "signals": 400}}, cp)
    c = sqlite3.connect(path)
    k = "day:" + ck.day_str(cp)
    st = json.loads(c.execute("SELECT data FROM state WHERE k = ?", (k,)).fetchone()[0])
    del st["engines"]["REEL_H1@5m"]
    c.execute("UPDATE state SET data = ? WHERE k = ?", (json.dumps(st), k))
    c.commit()
    c.close()
    v = ck.run_due(path, str(tmp_path / "c.db"), _minutes_for(), S, BR, SPECS, None, now_ms=cp + 1, n_bots=50,
                   log=lambda *_: None)[0]
    assert v["coverage"] == {"expected": {"core": 1, "reel": 1}, "found": {"core": 1}, "missing": ["REEL_H1@5m"]}
    r = v["accounts"]["REEL_H1@5m"]
    assert r["status"] == ck.HOLD and r["missing"] and r["group"] == "reel"
    assert any("상태 저장에 없는 계좌 1개 (5분 단타만 해당: REEL_H1@5m)" in w for w in v["warnings"])
    assert v["accounts"]["GOOD@1h"]["status"] == ck.PASS1
    view = ck.dashboard_view(str(tmp_path / "c.db"))
    assert {r["account_id"]: r["group"] for r in view["rows"]} == {"GOOD@1h": "core", "REEL_H1@5m": "reel"}
    # G20: each row's display group, verdict family and the family's alpha; the family alpha table on top
    fa = {r["account_id"]: (r["family"], r["alpha_family"]) for r in view["rows"]}
    assert fa == {"GOOD@1h": ("core", 0.07), "REEL_H1@5m": ("reel", 0.005)}
    assert view["family_alpha"] == ck.FAMILY_ALPHA
    assert [(f["family"], f["alpha"], f["judged_tfs"]) for f in view["family_table"]] == [
        ("core", 0.07, ["15m", "30m", "1h"]), ("ds200", 0.025, ["15m", "30m", "1h"]), ("reel", 0.005, ["5m"])]
    assert view["family_table"][0]["tested"] == 1 and view["method_ko"] == ck.method_ko(None, view["n_bots"])
    # jobs review 7: each family's expected lucky passes (verdict doc 6) on the dashboard too
    fam = {f["group"]: f for f in v["families"]}
    for row in view["family_table"]:
        if row["family"] in fam:
            assert (row["lucky_expected"], row["lucky_if_uncorrected"]) == (
                fam[row["family"]]["lucky_expected"], fam[row["family"]]["lucky_if_uncorrected"])
    assert view["family_table"][0]["lucky_if_uncorrected"] == pytest.approx(0.07)


def test_q5_warning_names_only_the_hit_group(tmp_path):
    from paperbot.store3 import Store3
    cp = T0 + 30 * DAY
    lo = T0 + 5 * 3_600_000
    path = str(tmp_path / "paper3.db")
    _paper_db(path, {"GOOD@1h": {"wallet": 400_000.0, "trades": _trades(40, lo, cp, 9875.0), "signals": 400},
                     "F3_BOS@1h": {"kind": "ds200", "wallet": 9000.0, "trades": _trades(40, lo, cp, 100.0),
                                   "signals": 400}}, cp)
    st = Store3(path)
    st.add_run(T0 + 10 * DAY, {"commit": "y", "changes": ["commit", "ds_code"]})
    st.close()
    v = ck.run_due(path, str(tmp_path / "c.db"), _minutes_for(), S, BR, SPECS, None, now_ms=cp + 1, n_bots=50,
                   log=lambda *_: None)[0]
    w = [x for x in v["warnings"] if "체결·청산·사이즈" in x]
    assert len(w) == 1 and "ds_code" in w[0] and "해당 묶음: 딥시크" in w[0]
    assert w[0] in v["accounts"]["F3_BOS@1h"]["notes"] and "notes" not in v["accounts"]["GOOD@1h"]
    assert "재시작 때 체결·청산·사이즈 코드 변경 (딥시크):" in v["text"]
    assert "묶음별 (FDR 나눔)\n- 매매법: 검정 1개 중 통과 1개 (FDR 7%) · 운으로 기대 ≤ 0.07개\n- 딥시크: 검정 1개 중 통과 " \
        in v["text"]


# ---------------------------------------------------------------------------- the reel's bots vs ReelEngine
def _reel_engine_run(m, lo, hi, sigs, five, s=S):
    w = m.window(lo, hi)
    row_of = {int(t): i for i, t in enumerate(five.ends)}
    engines = [ReelEngine(s, BR, symbol_specs=SPECS, book=f"r{i}") for i in range(sigs.shape[0])]
    bidx = {int(t): j for j, t in enumerate(sorted({int(t) for t in w.ts if t % FIVE == 0}))}
    for t in range(len(w.ts)):
        ts = int(w.ts[t])
        bars = {x: Bar(x, ts, ts + MIN - 1, w.o[t, k], w.h[t, k], w.l[t, k], w.c[t, k],
                       w.mo[t, k], w.mh[t, k], w.ml[t, k], w.mc[t, k]) for k, x in enumerate(V3_SYMBOLS)
                if not np.isnan(w.o[t, k])}                     # a missing 1m bar: the engine never sees it
        fund = {x: w.fr[t, k] for k, x in enumerate(V3_SYMBOLS) if not np.isnan(w.fr[t, k])}
        if ts in bidx and ts in row_of:
            r = row_of[ts]
            for i, e in enumerate(engines):
                for k, x in enumerate(V3_SYMBOLS):
                    a = five.atr[r, k]
                    if not sigs[i, bidx[ts], k] or not np.isfinite(a):
                        continue
                    stop = five.stop_low[r, k] - 0.05 * a
                    up = five.upper[r, k]
                    closes = five.close[r - BB_LEN + 2:r + 1, k]
                    if not (np.isfinite(stop) and np.isfinite(up)) or len(closes) != BB_LEN - 1:
                        continue
                    e.submit(Signal(ts=ts - 1, symbol=x, timeframe="5m", strategy_id="RANDOM_1", side=1,
                                    stop_price=float(stop), tier="best", tp_price=float(up), atr=float(a),
                                    meta={"ref_price": float(w.o[t, k]), "lev_group": "normal",
                                          "reel": {"closes": [float(c) for c in closes]}}))
        for e in engines:
            e.step(bars, fund)
    return engines


@pytest.mark.parametrize("kw,bust_below", [
    (dict(seed=21, vol=0.0012), 10.0),
    (dict(seed=22, vol=0.0008, gaps=0.002, gap_size=0.02, mark_wicks=0.003), 10.0),     # gaps, mark wicks: LIQ
    (dict(seed=23, vol=0.0008, gaps=0.002, gap_size=0.02, mark_wicks=0.003), 4800.0),   # the bust path
])
def test_reel_bots_match_reel_engine(kw, bust_below):
    s = v3_settings(bust_below=bust_below)
    lo = T0 + 2 * DAY
    hi = lo + 2 * DAY
    m = synth_minutes(T0, hi, **kw)
    five = ck.five_min_table(m)
    n_b = 16
    nb = int(np.count_nonzero(m.window(lo, hi).ts % FIVE == 0))
    rng = np.random.default_rng(6)
    sigs = rng.random((n_b, nb, 6)) < 0.03
    bounds = {int(t): j for j, t in enumerate(sorted(int(t) for t in m.window(lo, hi).ts if t % FIVE == 0))}

    def draw(ts, idx, rates, C):
        return sigs[idx, bounds[ts], :], np.ones((len(idx), C), int)

    res = ck.simulate_reel_bots(m, "5m", lo, hi, np.full(n_b, 0.03), s, BR, SPECS, draw=draw, five=five)
    engines = _reel_engine_run(m, lo, hi, sigs, five, s)
    _same(res, engines, s)
    reasons = {t.exit_reason for e in engines for t in e.trades}
    assert {"SL", "TP"} <= reasons and sum(len(e.trades) for e in engines) > 40
    skipped = [o for e in engines for o in e.outcomes if o.status == "SKIPPED" and o.reason.startswith("reel:")]
    assert skipped                                     # the skip rules were exercised
    if bust_below > 10:
        assert any(e.bust for e in engines)
    elif kw.get("mark_wicks"):
        assert "LIQ" in reasons


def _same(res, engines, s):
    for i, e in enumerate(engines):
        assert res["wallet"][i] == pytest.approx(e.wallet, rel=1e-9, abs=1e-6), (i, len(e.trades))
        assert res["trades"][i] == len(e.trades) + (e.position is not None), i
        assert bool(res["bust"][i]) == e.bust
        want = e.wallet
        if e.position is not None:
            p = e.position
            want += ck.open_value(p.side, p.qty, p.entry_price, p.margin, e._last_mark[p.symbol], s)
        assert res["equity"][i] == pytest.approx(want, rel=1e-9, abs=1e-6)


def _trend_minutes(lo, hi, slope=4e-5, noise=1e-6, seed=0):
    """A slow steady rise on every coin: the upper band stays out of reach and the swing-low stop far below, so
    the reel's trades end at the 96-bar time exit."""
    rng = np.random.default_rng(seed)
    m = ck.empty_minutes(lo, hi, V3_SYMBOLS)
    T = len(m.ts)
    for k in range(6):
        c = 100.0 * (1 + k) * np.exp(slope * np.arange(T) + rng.normal(0, noise, T))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1 + noise)
        lo_ = np.minimum(o, c) * (1 - noise)
        m.o[:, k], m.h[:, k], m.l[:, k], m.c[:, k] = o, h, lo_, c
        m.mo[:, k], m.mh[:, k], m.ml[:, k], m.mc[:, k] = o, h, lo_, c
        f = (m.ts % (8 * 3_600_000)) == 0
        m.fr[f, k] = 0.0001
    return m


def test_reel_bots_time_exit_and_a_missing_minute_match_reel_engine():
    lo = T0 + 2 * DAY
    hi = lo + DAY
    m = _trend_minutes(T0 + DAY, hi)
    n_b = 6
    bounds = sorted(int(t) for t in m.window(lo, hi).ts if t % FIVE == 0)
    sigs = np.zeros((n_b, len(bounds), 6), bool)
    for i in range(n_b):
        sigs[i, 2 + 7 * i, i] = True                      # bot i: one signal on coin i
    # bot 0's time exit minute (the last 1m bar of its 96th 5m bar) is missing for coin 0: it exits at the next open
    end0 = bounds[2] + 96 * FIVE
    j = int(np.searchsorted(m.ts, end0 - MIN))
    for name in ("o", "h", "l", "c", "mo", "mh", "ml", "mc"):
        getattr(m, name)[j, 0] = np.nan
    five = ck.five_min_table(m)
    idx = {t: q for q, t in enumerate(bounds)}

    def draw(ts, ix, rates, C):
        return sigs[ix, idx[ts], :], np.ones((len(ix), C), int)
    res = ck.simulate_reel_bots(m, "5m", lo, hi, np.full(n_b, 0.01), S, BR, SPECS, draw=draw, five=five)
    engines = _reel_engine_run(m, lo, hi, sigs, five)
    _same(res, engines, S)
    assert all([t.exit_reason for t in e.trades] == ["TIME"] for e in engines)
    assert engines[0].trades[0].exit_time == end0 and engines[1].trades[0].exit_time == bounds[9] + 96 * FIVE - 1


def test_reel_bots_through_simulate_bots_and_time_exit():
    lo = T0 + 2 * DAY
    hi = lo + 2 * DAY
    m = synth_minutes(T0, hi, seed=31, vol=0.0003)          # quiet: targets and stops far, 8 h time exits happen
    a = ck.simulate_bots(m, "5m", lo, hi, np.full(30, 0.02), S, BR, SPECS, seed=[3, 4], exits="reel")
    b = ck.simulate_reel_bots(m, "5m", lo, hi, np.full(30, 0.02), S, BR, SPECS, seed=[3, 4])
    assert all((a[k] == b[k]).all() for k in ("equity", "wallet", "trades", "bust"))
    assert a["trades"].sum() > 0
    with pytest.raises(ValueError):
        ck.simulate_bots(m, "15m", lo, hi, np.full(3, 0.02), S, BR, SPECS, exits="reel")


def test_a_final_verdict_stays_final_when_the_account_is_missing():
    cp = T0 + 60 * DAY
    snap = _snap(cp, {"A@1h": _acct("1h", 40, 9000.0, T0, cp)})
    snap["coverage"] = {"expected": {"core": 3}, "found": {"core": 1}, "missing": [
        {"account_id": "B@1h", "strategy": "B", "timeframe": "1h", "kind": "strategy", "created_ts": T0,
         "parent": None, "group": "core"},
        {"account_id": "C@1h", "strategy": "C", "timeframe": "1h", "kind": "strategy", "created_ts": T0,
         "parent": None, "group": "core"}]}
    prior = {"B@1h": {"date": ck.day_str(T0 + 30 * DAY), "status": ck.FAIL, "stage": "1차", "reason": "1차: 파산",
                      "p": 0.5, "q": 0.9},
             "C@1h": {"date": ck.day_str(T0 + 30 * DAY), "status": ck.PASS1, "stage": "1차",
                      "window": [T0, T0 + 30 * DAY]}}
    rows, tasks = ck.plan(snap, prior, {}, S)
    assert rows["B@1h"]["status"] == ck.FAIL and "판정 유지" in rows["B@1h"]["reason"] and rows["B@1h"]["missing"]
    assert rows["C@1h"]["status"] == ck.HOLD and rows["C@1h"]["missing"] and [t.aid for t in tasks] == ["A@1h"]


def test_method_ko_is_built_from_the_code_never_typed():
    """G18: one short Korean line per group from N_BOTS, FAMILY_ALPHA and the judged timeframes (the owners' texts
    read it instead of "동전 봇 2,000개 + FDR 10%")."""
    whole = ck.method_ko()
    assert f"동전 봇 {ck.N_BOTS:,}개" in whole and "2,000" not in whole and "FDR 10%" not in whole
    assert "매매법 7%(15분·30분·1시간) · 딥시크 2.5%(15분·30분·1시간) · 5분 단타 0.5%(5분) · 합계 10%" in whole
    assert "운 기준 FDR 2.5% · 판정 봉 15분·30분·1시간 · 4시간봉은 관찰용" in ck.method_ko("ds200")
    assert ck.method_ko("reel").endswith("5분 단타 묶음 운 기준 FDR 0.5% · 판정 봉 5분")
    assert ck.method_ko("extra") == ck.method_ko("core") and "복사·새 매매법" in ck.method_ko("core")
    assert "판정 안 함" in ck.method_ko("flip")
    assert f"동전 봇 {ck.REHEARSAL_BOTS:,}개" in ck.method_ko("core", ck.REHEARSAL_BOTS)
    # the observe reasons say which timeframes a family judges (no "5분봉 ... 뺐음" of the v3 run)
    import inspect
    assert "뺐음" not in inspect.getsource(ck)
