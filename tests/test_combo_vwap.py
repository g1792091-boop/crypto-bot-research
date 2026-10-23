"""'VWAP 개선판' (owners 2026-10-23, deploy/combo.vwap.json: VWAP fail 30m + CMO sandwich 1h): the entry gates
(paperbot/entrygates.py: the trend judges' vote on the last closed 4h bar, ATR% above its 30-day 80 % point), the time
limit (combo ``max_hold_bars`` of the position's own timeframe, exit "TIME") and that the running bots' configs do not
change."""

from __future__ import annotations

import json
from pathlib import Path
import math
import os

import numpy as np
import pandas as pd
import pytest

from paperbot import combo as C
from paperbot import entrygates as G
from paperbot.trendjudge import Judge, Klines, TrendRules

from test_combo import MIN, PX, T0, World, cfg_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H4 = 4 * 3_600_000
M30 = 30 * MIN


def _deploy(name):
    with open(os.path.join(ROOT, "deploy", name), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- configs
def test_deploy_config_is_candidate_a_and_valid():
    raw = _deploy("combo.vwap.json")
    cfg = C.ComboConfig.from_dict(raw)
    assert cfg.problems() == []
    assert [(m["strategy"], m["tf"]) for m in cfg.members] == [("F6_VWAP_FAIL", "30m"), ("S3_CMO_SANDWICH", "1h")]
    assert cfg.vote_gate == {"tf": "4h", "vote_min": 3}
    assert cfg.vol_gate == {"atr": 14, "days": 30, "q": 0.8}
    assert cfg.max_hold_bars == 96 and cfg.margin == 0.4
    assert cfg.stop == {"mode": "atr", "atr": 2} and cfg.ladder == {"first_lock": 0.10, "trigger_gap": 0.02, "step": 0.05}
    assert cfg.lev_of("BTCUSDT") == cfg.lev_of("DOGEUSDT") == 30 and cfg.loss_cap == "shrink"
    assert cfg.max_loss_frac == pytest.approx(0.5 * cfg.margin)          # the stop loses at most 50 % of the margin
    assert cfg.no_weekend and cfg.macro_blackout_min == 30 and cfg.us_open_pause_min == cfg.us_open_pre_min == 30
    assert cfg.early_exit is None and cfg.trend is None and cfg.rank == ("order",)
    assert cfg.db != _deploy("combo.trend.json")["db"]                   # its own database, its own account


@pytest.mark.parametrize("name", ["combo.trend.json", "combo.live15.json", "combo.live15-mexc.json"])
def test_running_bots_have_none_of_it(name):
    cfg = C.ComboConfig.from_dict(_deploy(name))
    assert cfg.vote_gate is None and cfg.vol_gate is None and cfg.max_hold_bars is None
    assert C.gate_lines(cfg) == []


def test_config_problems(tmp_path):
    ok = cfg_of(tmp_path, members=[{"strategy": "V39_ALL", "tf": "30m"}], vote_gate={"tf": "4h", "vote_min": 3},
                vol_gate={"atr": 14, "days": 30, "q": 0.8}, max_hold_bars=96)
    assert ok.problems() == []
    bad = {"vote_gate": [{"tf": "15m"}, {"vote_min": 5}, {"vote_min": True}, {"tf": "4h", "x": 1}, "4h"],
           "vol_gate": [{"q": 1.2}, {"atr": 1}, {"days": 40}, {"days": 30.5}, {"y": 2}, []],
           "max_hold_bars": [0, True, 96.0, 5000]}
    for k, vals in bad.items():
        for v in vals:
            probs = cfg_of(tmp_path, members=[{"strategy": "V39_ALL", "tf": "30m"}], **{k: v}).problems()
            assert any(k in p for p in probs), (k, v, probs)
    assert any("vol_gate" in p for p in cfg_of(tmp_path, members=[{"strategy": "V39_ALL", "tf": "1d"}],
                                                vol_gate={}).problems())
    with pytest.raises(C.ComboError):
        C.ComboConfig.from_dict({"paper_db": "a", "db": "b", "members": [], "vwap_gate": {}})


def test_words():
    cfg = C.ComboConfig.from_dict(_deploy("combo.vwap.json"))
    lines = C.gate_lines(cfg)
    assert lines == ["4시간 추세 판단이 반대면 진입 안 함(4개 중 3개 반대; 보류는 진입)",
                     "변동성(ATR14%)이 지난 30일의 80% 위치보다 크면 진입 안 함(상위 20% 금지)",
                     "보유 한도 96봉(30분 48시간 · 1시간 96시간), 넘으면 시장가 청산"]
    text = C.start_text(cfg, C.resolve_members(cfg.members, cfg.picks_file), 1000.0)
    assert text.startswith("[합친 봇 페이퍼 VWAP 개선판] 시작:") and all(x in text for x in lines)
    assert text.endswith("포지션 1개, 진입 쉼 주말·경제 발표 앞뒤 30분·나스닥 개장 앞 30분·뒤 30분, 지갑 $1,000.00")


# ---------------------------------------------------------------- the volatility gate
def _bars30(n, end_open, seed=5, spike=None):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    w = np.abs(rng.normal(0, 0.002, n)) + 0.001
    if spike is not None:
        w[-spike:] *= 6
    h, l = np.maximum(o, c) * (1 + w), np.minimum(o, c) * (1 - w)
    t = end_open - (n - 1 - np.arange(n)) * M30
    return [[int(t[i]), float(o[i]), float(h[i]), float(l[i]), float(c[i]), 1.0] for i in range(n)]


def test_atr_pct_and_quantile_equal_the_research_formula():
    rows = np.array(_bars30(2400, T0), dtype=float)
    h, l, c = rows[:, 2], rows[:, 3], rows[:, 4]
    # research/vwap30/code/vwcommon.atr_adx + vwbuild.features on the whole series
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    atrp = atr / c
    q80 = pd.Series(atrp).rolling(1440, min_periods=720).quantile(0.8).to_numpy()
    for end in (900, 1800, 2399):
        s = slice(max(0, end - 1739), end + 1)              # the gate's 1740 bars (fewer at the series start)
        a, q = G.atr_pct_and_q(h[s], l[s], c[s], 14, 1440, 0.8)
        assert a == pytest.approx(atrp[end], rel=1e-9) and q == pytest.approx(q80[end], rel=1e-9)
    a, q = G.atr_pct_and_q(h[:500], l[:500], c[:500], 14, 1440, 0.8)
    assert math.isnan(q) and math.isnan(q80[499]) and a == pytest.approx(atrp[499])       # too few: passes


class Feed:
    def __init__(self, rows):
        self.rows, self.calls, self.fail = rows, [], False

    def __call__(self, symbol, tf, start, limit):
        self.calls.append((symbol, tf, start, limit))
        if self.fail:
            raise OSError("down")
        return [r for r in self.rows if r[0] >= start][:limit]


def test_vol_gate_blocks_the_top_20_percent_only_and_reads_closed_bars():
    sig = T0 + 2000 * M30                                   # the signal bar opens at sig - 30m and closes at sig
    calm = Feed(_bars30(2000, sig - M30) + [[sig, 1, 1, 1, 1, 1]])          # the forming bar is never used
    now = [sig + 61_000]
    g = G.EntryGates(vol={"atr": 14, "days": 30, "q": 0.8}, bars=G.BarCache(calm, lambda: now[0]))
    why = g.block("ETHUSDT", "30m", 1, sig)
    assert why == "" or why.startswith("변동성 높음")
    assert len(calm.calls) == 2 and calm.calls[0][2] == sig - M30 - (1440 + G.WARM - 1) * M30   # 1740 bars: 2 pages
    spiky = Feed(_bars30(2000, sig - M30, spike=3))
    g2 = G.EntryGates(vol={}, bars=G.BarCache(spiky, lambda: now[0]))
    why, info = g2.check("ETHUSDT", "30m", -1, sig)
    assert why.startswith("변동성 높음: ATR ") and info["vol"]["atr_pct"] > info["vol"]["q_pct"]
    assert info["vol"]["text"].startswith("변동성 30분 ATR ") and "(30일 80% 위치 " in info["vol"]["text"]
    # next bar: one short read from the last bar held (no full reload)
    spiky.rows = _bars30(2001, sig, spike=3)
    now[0] = sig + M30 + 61_000
    g2.block("ETHUSDT", "30m", 1, sig + M30)
    assert spiky.calls[-1][2] == sig and len(spiky.calls) == 3


def test_vol_gate_cannot_read_bars_blocks_and_backs_off():
    sig = T0 + 2000 * M30
    f = Feed(_bars30(2000, sig - M30))
    f.fail = True
    now = [sig + 61_000]
    g = G.EntryGates(vol={}, bars=G.BarCache(f, lambda: now[0]))
    why = g.block("SOLUSDT", "30m", 1, sig)
    assert why.startswith("변동성 판단에 쓸 30분봉을 못 읽음(진입 안 함)") and "down" in why
    assert g.block("SOLUSDT", "30m", 1, sig).startswith("변동성 판단에 쓸")
    assert len(f.calls) == 1                                # waits RETRY_MS before the next read
    f.fail = False
    now[0] += G.RETRY_MS
    assert not g.block("SOLUSDT", "30m", 1, sig).startswith("변동성 판단에 쓸")
    # a bar not closed yet (asked right at its close): not readable, never the bar before
    f2 = Feed(_bars30(2001, sig))
    g3 = G.EntryGates(vol={}, bars=G.BarCache(f2, lambda: sig + M30 + 1_000))
    assert g3.block("SOLUSDT", "30m", 1, sig + M30).startswith("변동성 판단에 쓸")


# ---------------------------------------------------------------- the 4h vote gate
def _bars4h(n, end_open, drift):
    rng = np.random.default_rng(11)
    c = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
    v = 100 + 50 * (c > o)
    t = end_open - (n - 1 - np.arange(n)) * H4
    return [[int(t[i]), float(o[i]), float(h[i]), float(l[i]), float(c[i]), float(v[i])] for i in range(n)]


def _vote_gate(rows, now):
    k = Klines(lambda s, tf, n: [r for r in rows if r[0] <= now[0]][-n:], lambda: now[0])
    return G.EntryGates(vote={"tf": "4h", "vote_min": 3}, judge=Judge(k, TrendRules(vote_min=3)))


def test_vote_gate_blocks_only_the_side_against_the_4h_vote():
    b4 = T0 - T0 % H4                                        # a 4h close; the signal's 30m bar closes there too
    now = [b4 + 61_000]
    up = _vote_gate(_bars4h(400, b4 - H4, 0.01), now)
    why, info = up.check("BTCUSDT", "30m", 1, b4)
    assert why == "" and info["vote"]["text"] == "4시간 상승(상승 4·하락 0·중립 0)" and info["vote"]["with_side"] == 1
    assert info["vote"]["bar_close"] == b4 and "vol" not in info
    assert up.block("BTCUSDT", "30m", -1, b4) == "4시간 추세 반대: 상승 4·하락 0·중립 0"
    down = _vote_gate(_bars4h(400, b4 - H4, -0.01), now)
    assert down.block("BTCUSDT", "30m", 1, b4).startswith("4시간 추세 반대")
    assert down.block("BTCUSDT", "30m", -1, b4) == ""
    # a 30m signal inside the 4h bar reads the 4h bar closed before it (the same judgment)
    assert up.block("BTCUSDT", "30m", -1, b4 + 2 * M30) == up.block("BTCUSDT", "30m", -1, b4)


def test_vote_gate_neutral_passes_and_unreadable_blocks():
    b4 = T0 - T0 % H4
    now = [b4 + 61_000]
    flat = _vote_gate(_bars4h(400, b4 - H4, 0.0), now)
    j = flat.judge.judgment("BTCUSDT", "4h", b4)
    for side in (1, -1):
        assert (flat.block("BTCUSDT", "30m", side, b4) == "") == (j.raw != -side)
    few = _vote_gate(_bars4h(50, b4 - H4, 0.01), now)        # fewer than trendjudge.MIN_BARS
    assert few.block("BTCUSDT", "30m", 1, b4).startswith("4시간 추세 판단을 못 읽음(진입 안 함)")


def test_vote_gate_equals_the_research_judge_files_raw3():
    """The research's j4h (research/newlive judge files) is trendjudge.raw_votes(vote_arrays(...), 3) on closed 4h bars;
    the gate reads the same on the last 300 of them."""
    from paperbot.trendjudge import raw_votes, vote_arrays
    rows = _bars4h(700, T0 - T0 % H4 - H4, 0.0005)
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df.t, unit="ms")
    full = raw_votes(vote_arrays(df), 3)
    for i in (450, 600, 699):
        now = [int(rows[i][0]) + H4 + 61_000]
        g = _vote_gate(rows, now)
        assert g.judge.judgment("ETHUSDT", "4h", int(rows[i][0]) + H4).raw == int(full[i])


# ---------------------------------------------------------------- in the runner
INFO = {"vote": {"tf": "4h", "up": 3, "down": 0, "raw": 1, "text": "4시간 상승(상승 3·하락 0·중립 1)"},
        "vol": {"tf": "15m", "atr_pct": 0.3, "q_pct": 0.5, "text": "변동성 15분 ATR 0.30% (30일 80% 위치 0.50%)"}}


class Stub:
    def __init__(self, why):
        self.why, self.asked = why, []

    def check(self, symbol, tf, side, bar_close):
        self.asked.append((symbol, tf, side, bar_close))
        return self.why(symbol, side), INFO

    def block(self, symbol, tf, side, bar_close):
        return self.check(symbol, tf, side, bar_close)[0]


def _world(tmp_path, gates=None, **kw):
    w = World(tmp_path, **kw)
    w.run.gates = gates
    w.now = T0 + 5_000
    w.run.poll()
    return w


def test_runner_filters_a_gated_signal_and_enters_the_next_coin(tmp_path):
    stub = Stub(lambda s, side: "4시간 추세 반대: 상승 0·하락 3·중립 1" if s == "BTCUSDT" else "")
    w = _world(tmp_path, stub)
    B = T0 + 15 * MIN
    w.add_minutes(T0, 15)
    w.signal("V39_ALL", "BTCUSDT", 1, B)
    w.signal("V39_ALL", "ETHUSDT", 1, B)
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert sorted(stub.asked) == [("BTCUSDT", "15m", 1, B), ("ETHUSDT", "15m", 1, B)]
    p = w.engine().position
    assert p.symbol == "ETHUSDT"
    # what the gates read rides with the entry (the trade record keeps ctx) and with the filtered signal's row
    assert p.signal.meta["gates"] == INFO and p.signal.meta["ctx"]["gates"] == INFO
    rows = {r[0]: (r[1], json.loads(r[2])) for r in w.store.conn.execute("SELECT symbol, status, data FROM signal_log")}
    assert rows["BTCUSDT"][0] == "FILTERED" and rows["BTCUSDT"][1]["gates"] == INFO
    assert rows["BTCUSDT"][1]["why"].startswith("4시간 추세 반대")
    assert w.run.counts["V39_ALL@15m"]["filtered"] == 1
    text = C.entry_text(w.cfg, p)
    assert text.startswith("[합친 봇 페이퍼] 진입 ETH 롱 · V3.9 15분 · ") or text.startswith("[합친 봇 페이퍼] 진입 ETH 롱 · ")
    assert text.endswith("· 4시간 상승(상승 3·하락 0·중립 1) · 변동성 15분 ATR 0.30% (30일 80% 위치 0.50%)")


def test_weekend_is_checked_before_the_gates(tmp_path):
    stub = Stub(lambda s, side: "x")
    w = _world(tmp_path, stub, no_weekend=True)
    sat = T0 + 5 * 86_400_000 - 9 * 3_600_000 + 15 * MIN      # Saturday 00:15 KST
    sig = C.make_signal(w.cfg, w.members[0], sat, "BTCUSDT", 1, 100.0, PX["BTCUSDT"], sat, 0, None, "rule")
    assert w.run._entry_block(sig, sat, sat, {}).startswith("주말") and stub.asked == []


# ---------------------------------------------------------------- the time limit
def _open(w):
    B = T0 + 15 * MIN
    w.add_minutes(T0, 15)
    w.signal("V39_ALL", "BTCUSDT", 1, B)
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position is not None and w.engine().position.entry_time == B
    return B


def test_max_hold_closes_at_the_open_of_the_minute_it_runs_out(tmp_path):
    w = _world(tmp_path, max_hold_bars=4)              # 4 bars of 15m
    B = _open(w)
    w.add_minutes(B + MIN, 59)                             # minutes B+1 .. B+59: still open
    w.now = B + 60 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is not None
    w.add_minutes(B + 60 * MIN, 1)
    w.now = B + 61 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is None
    t = json.loads(w.store.conn.execute("SELECT data FROM trades WHERE account_id = ?", (C.ACCOUNT,)).fetchone()[0])
    assert t["exit_reason"] == "TIME" and t["exit_time"] == B + 60 * MIN
    assert abs(t["exit_price"] - w.px["BTCUSDT"] * (1 - 0.0002)) < 1e-6
    assert t["context"]["exit_why"] == "보유 4봉(1시간) 한도"
    assert "감독 청산(시간 정리)(보유 4봉(1시간) 한도)" in C.exit_text(w.cfg, w.engine().trades[-1])


def test_max_hold_minute_may_enter_the_next_signal(tmp_path):
    w = _world(tmp_path, max_hold_bars=4)              # 4 bars of 15m
    B = _open(w)
    w.add_minutes(B + MIN, 59)
    E = B + 60 * MIN
    w.signal("OBV_S", "ETHUSDT", -1, E)
    w.add_minutes(E, 1)
    w.now = E + 65_000
    w.run.poll()
    p = w.engine().position
    assert p is not None and p.symbol == "ETHUSDT" and p.entry_time == E
    assert w.engine().trades[-1].exit_reason == "TIME"


def test_no_max_hold_keeps_the_position(tmp_path):
    w = _world(tmp_path)
    B = _open(w)
    w.add_minutes(B + MIN, 3 * 60)
    w.now = B + 181 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is not None


def test_executor_follows_time_before_its_own_lock():
    from paperbot.executor import BEFORE_LOCK_EXITS, PAPER_EXIT_KO
    assert "TIME" in BEFORE_LOCK_EXITS and PAPER_EXIT_KO["TIME"] == C.KO_EXIT["TIME"]


def test_max_hold_counts_bars_of_the_positions_own_timeframe(tmp_path):
    cfg = cfg_of(tmp_path, max_hold_bars=96)
    assert C.hold_minutes(cfg, "30m") == 96 * 30 and C.hold_minutes(cfg, "1h") == 96 * 60
    assert C.hold_minutes(cfg_of(tmp_path), "30m") is None


def test_unit_and_install_never_start_it():
    unit = (Path(ROOT) / "deploy" / "paperbot-combo-vwap.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.combo run --config /etc/paperbot/combo-vwap.json" in unit
    assert "ReadWritePaths=/var/lib/paperbot/combo\n" in unit and "-/etc/paperbot/executor.env" in unit
    inst = (Path(ROOT) / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert 'install -m 644 "$APP/deploy/paperbot-combo-vwap.service" /etc/systemd/system/paperbot-combo-vwap.service' in inst
    assert "enable --now paperbot-combo-vwap" not in inst and "start paperbot-combo-vwap" not in inst
    units = next(x for x in inst.splitlines() if x.startswith("UNITS="))
    assert "paperbot-combo-vwap" in units.split('"')[1].split()          # stopped for the code swap, started again
    assert "combo/vwap" in (Path(ROOT) / "deploy" / "paperbot-backup.sh").read_text(encoding="utf-8")
