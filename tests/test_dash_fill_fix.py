"""Review fixes on the fill branches (fill-fix): D10/D11 in mixed lists, the risk ladder's pulse, the radar's Binance
load, and the small honesty words.

- derive.ranked / rankedOnly in 전체: DeepSeek and coin flips come last, by name, with no rank (node);
- countOnly: a DeepSeek / coin-flip position or trade shows no money outside its own group (node + wiring greps);
- the risk ladder pulses only near the liquidation or a losing stop, never for a lock line (node);
- the radar moves a kept cell on by one small request (TAIL bars) per new bar, a gap falls back to the full window;
- people.py turns a read error into an honest error field (no 500); small words (아직 없음, 어제, 표본 적음).
"""
import json
import os
import shutil
import sqlite3
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "paperbot", "dash", "static", "v4")
SCR = os.path.join(V4, "screens")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return fh.read()


def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    imp = {k: os.path.abspath(os.path.join(V4, *v.split("/"))) for k, v in {
        "D": "core/derive.js", "K": "screens/positions-kit.js", "RK": "screens/positions-risk.js",
        "RD": "screens/strategies-radar.js", "M": "screens/market-live.js", "F": "core/fmt.js"}.items()}
    script = "".join(f"const {k} = await import('{p}');\n" for k, p in imp.items()) + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_mixed_ranking_counts_deepseek_and_coin_only():
    out = _node("""
const acc = (id, kind, wallet, trades = 3) => ({account_id: id, kind, timeframe: "1h", strategy: id, wallet, trades});
const board = {initial: 5000, accounts: [acc("c1", "strategy", 5100), acc("c2", "strategy", 4900), acc("ds_b", "ds200", 6000),
  acc("ds_a", "ds200", 4000), acc("r1", "random", 7000), acc("c0", "strategy", 5000, 0)]};
const all = D.ranked(board, "all").map((a) => a.account_id);
const only = D.rankedOnly(board, "all");
const core = D.ranked(board, "coin").map((a) => a.account_id);
console.log(JSON.stringify({all, only: only.rows.map((a) => a.account_id), waiting: only.waiting, core,
  co: [D.countOnlyIn(board.accounts[2], "all"), D.countOnlyIn(board.accounts[2], "ds"), D.countOnlyIn(board.accounts[4], ""),
       D.countOnlyIn(board.accounts[0], "all"), K.countOnly({kind: "ds200"}, ""), K.countOnly({group: "flip"}, "coin")]}));
""")
    # money accounts by return (the unranked one after), then DeepSeek by name, then the coin flip, whatever they made
    assert out["all"] == ["c1", "c2", "c0", "ds_a", "ds_b", "r1"]
    assert out["only"] == ["c1", "c2"] and out["waiting"] == 1
    assert out["core"] == ["r1"]                                            # its own group: unchanged
    assert out["co"] == [True, False, True, False, True, False]


def test_risk_ladder_pulses_for_danger_only():
    out = _node("""
const mk = (side, entry, stop, liq) => ({pos: {side, entry, stop, liq, symbol: "BTCUSDT"}});
const m = 100;
const lock = {...mk(1, 95, 99.8, 70), dLiq: RK.gap(1, m, 70), dStop: RK.gap(1, m, 99.8)};       // stop above entry: profit
const loss = {...mk(1, 101, 99.8, 70), dLiq: RK.gap(1, m, 70), dStop: RK.gap(1, m, 99.8)};      // stop below entry
const far = {...mk(-1, 100, 103, 104), dLiq: RK.gap(-1, m, 104), dStop: RK.gap(-1, m, 103)};
const liq = {...mk(-1, 99, 99.9, 100.3), dLiq: RK.gap(-1, m, 100.3), dStop: RK.gap(-1, m, 99.9)};  // short lock, liq 0.3%
console.log(JSON.stringify({near: RK.NEAR, isLock: [RK.isLock(lock.pos), RK.isLock(loss.pos)],
  danger: [RK.danger(lock), RK.danger(loss), RK.danger(far), RK.danger(liq)]}));
""")
    assert out["near"] == 0.005
    assert out["isLock"] == [True, False]
    assert out["danger"] == [False, True, False, True]


def test_radar_reload_after_the_bot_and_one_recheck():
    out = _node("""
const bc = 1000000, nc = bc + 900000;
const plain = RD.nextLoadAt({bar_close: bc, next_close: nc, rows: [{left: 1}]}, bc + 50000);
const wait = RD.nextLoadAt({bar_close: bc, next_close: nc, rows: [{left: 0, fired: null}]}, bc + 50000);
const after = RD.nextLoadAt({bar_close: bc, next_close: nc, rows: [{left: 0, fired: null}]}, bc + 95000);
const fired = RD.nextLoadAt({bar_close: bc, next_close: nc, rows: [{left: 0, fired: {long: true}}]}, bc + 50000);
const stale = RD.nextLoadAt({bar_close: bc, next_close: bc, rows: []}, bc + 5000);
console.log(JSON.stringify({plain: plain - nc, wait: wait - bc, after: after - nc, fired: fired - nc, stale: stale - bc - 5000,
  ac: RD.AFTER_CLOSE}));
""")
    assert out["ac"] >= 45000
    assert out["plain"] == out["ac"] and out["fired"] == out["ac"] and out["after"] == out["ac"]
    assert out["wait"] == out["ac"] + 45000                                   # one more look for a late signal
    assert out["stale"] == 20000


def test_when_ko_says_yesterday():
    out = _node("""
const mid = F.kstMidnight(Date.now());
console.log(JSON.stringify({y: M.whenKo(mid - 3600000), t: M.whenKo(mid + 60000), n: M.whenKo(null)}));
""")
    assert out["y"].startswith("어제 ") and not out["t"].startswith("어제") and out["n"] == "—"


def _frames(calls, state):
    import pandas as pd

    def frames(sym, tf, n):
        calls.append((sym, tf, n))
        end = state["end"]            # index of the newest closed bar
        idx = list(range(end - n + 1, end + 1))
        ts = pd.to_datetime([1_700_000_000_000 + i * 3_600_000 for i in idx], unit="ms", utc=True)
        return pd.DataFrame({"ts": ts, "open": [float(i) for i in idx], "high": [float(i) + 1 for i in idx],
                             "low": [float(i) - 1 for i in idx], "close": [float(i) for i in idx], "volume": [1.0] * n})
    return frames


def test_radar_cell_moves_on_with_one_small_request(monkeypatch):
    pytest.importorskip("pandas")
    from paperbot.dash import app as A
    from paperbot.dash.more import radar as R
    monkeypatch.setattr(A, "view_bars", lambda tf, strategy=None: 300)
    calls, state = [], {"end": 1000}
    clock = {"t": (1_700_000_000_000 + 1001 * 3_600_000) / 1000 + 10}      # 10 s after bar 1000 closed
    rd = R.Radar(_frames(calls, state), None, now=lambda: clock["t"])
    c1 = rd.cell("1h", "BTCUSDT")
    assert [n for _s, _tf, n in calls] == [300] and len(c1["df"]) == 300
    state["end"] = 1001
    clock["t"] += 3600
    c2 = rd.cell("1h", "BTCUSDT")
    assert [n for _s, _tf, n in calls] == [300, R.TAIL]                      # one small request, weight 1
    full = _frames([], state)("BTCUSDT", "1h", 300)
    assert len(c2["df"]) == 300 and list(c2["df"]["close"]) == list(full["close"])      # same window as a fresh fetch
    assert c2["df"].index[0] == 0
    state["end"] = 1020                                                      # asleep: a gap longer than the tail
    clock["t"] += 19 * 3600
    c3 = rd.cell("1h", "BTCUSDT")
    assert [n for _s, _tf, n in calls] == [300, R.TAIL, R.TAIL, 300]
    assert c3["df"]["close"].iloc[-1] == 1020.0 and len(c3["df"]) == 300
    assert "SMT" not in _read(HERE, "..", "paperbot", "dash", "more", "radar.py")


def test_people_read_error_is_an_honest_state(tmp_path):
    from paperbot.dash.more import people as P
    db = str(tmp_path / "p.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE unrelated (x)")
    c.commit()
    c.close()
    for v in (P.today_view(db, 1_790_000_000_000), P.strats_view(db, 1_790_000_000_000),
              P.strat_view(db, "V1.1", 1_790_000_000_000)):
        assert "읽지 못함" in v["error"]
    assert P.strat_view(db, "V1.1", 1_790_000_000_000)["signals"] is None


def test_wiring_count_only_and_words():
    pos = _read(SCR, "positions.js")
    assert "countOnly: co(x)" in pos and "countOnly(t, st.tGrp)" in pos and "합계에서 뺌" in pos
    kit = _read(SCR, "positions-kit.js")
    assert "const co = !!o.countOnly;" in kit and "co ? null : stopLine(a, pos)" in kit
    assert 'derive.countOnlyIn(a, view)' in kit
    chart = _read(SCR, "chart.js")
    # the position lines moved to the shared chart deck helper (chart-lines.js, used by 차트 and the terminal)
    assert 'g.items.filter((x) => !countOnly(x.a, ""))' in _read(SCR, "chart-lines.js") and "posLines(" in chart and "usdKo(t.q)" in chart
    cp = _read(SCR, "chart-panels.js")
    assert 'countOnly(x.a, "")' in cp and "usdShort(" in cp          # liquidation sizes: one money format ($K / $M, core/liqkit.js), term-plus
    hs = _read(SCR, "home-shared.js")
    assert 'derive.countOnlyIn(a, "all")' in hs and "derive.mixedOrder(" in hs
    assert "derive.mixedOrder(" in _read(SCR, "board-table.js")
    assert "derive.countOnlyIn(a, st.sel)" in _read(SCR, "board-motion.js")
    assert 'Array.isArray(d.signals) ? "아직 없음" : "수집 전"' in _read(SCR, "rooms-record.js")
    hl = _read(SCR, "home-live.js")
    # today's best / worst from the server's day sums (summary today.by_group.core: every trade, no 2,000-row cap)
    assert "표본 적음" in hl and "bestWorstOf(" in hl and "limit=2000" not in hl
    grid = _read(SCR, "grid.css")
    assert ".gk-cell.pos.off { background: var(--surface); color: var(--muted); }" in grid
    assert ".gk-cell.y5 small, .gk-cell.pos small { font-size: var(--t-xs); }" in grid
    css = _read(SCR, "strategies.css")
    assert "repeat(3, minmax(0, 1fr))" not in css.split("fill-strat: the chart")[1]                     # 2 columns only
    assert ".strat-prow.strat-hot { padding-left:" in css
