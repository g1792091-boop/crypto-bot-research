"""한눈 지도 + 매매법 프로필 카드 (dash/more/grid.py) on a small synthetic paper3.db.

Checks: one cell per original account (copies left out), the window return (realized wallet now / realized wallet at
the window start), trades and wins inside the window, the same-timeframe coin-flip median and the difference for the
36 and the reel (the reel against its three 5m flips), none for DeepSeek or a coin flip; the session definitions
without a 4h account; the 30-day window covering a young run equals the board; the 7-day window reads the balance
before it; the summed curves of the list; the profile card (drawdown from the engine for the whole run, from the
5-minute samples inside a shorter window, the curve and the coin flips' median ghost, DeepSeek at group level only,
a coin flip as the yardstick); a strategy card; 404s; an empty database; incremental reads; the cache (re-entrant: a
card asks for the cached grid inside it); the database is never written; the answer for 331 accounts stays small; and
the honesty wording and colours in the page files."""

import calendar as _cal
import hashlib
import json
import os
import re
import sqlite3
import threading

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import Data, create_app, hash_password  # noqa: E402
from paperbot.dash.more import grid as GR  # noqa: E402
from paperbot.store3 import SCHEMA  # noqa: E402

DAY = 86_400_000
H = 3_600_000
INIT = 5000.0
START = _cal.timegm((2026, 9, 26, 5, 0, 0)) * 1000
NOW = START + 10 * DAY
PW = "correct horse battery"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")

# account -> (kind, wallet now, [(day, pnl)], max_drawdown)
WORLD = {
    "S5_DONCHIAN_MFI@15m": ("strategy", 5250.0, [(1, 100.0), (5, -50.0), (8, 200.0)], 0.12),
    "S5_DONCHIAN_MFI@4h": ("strategy", 4950.0, [(2, -50.0)], 0.03),
    "F9_FVG@15m": ("ds200", 4800.0, [(4, -200.0)], 0.05),
    "F15_ASIA_BRK@15m": ("ds200", 5000.0, [], 0.0),
    "REEL_H1@5m": ("reel", 5100.0, [(6, 100.0)], 0.02),
    "RANDOM_1@15m": ("random", 4900.0, [(2, -100.0)], 0.02),
    "RANDOM_2@15m": ("random", 5000.0, [], 0.0),
    "RANDOM_3@15m": ("random", 5100.0, [(9, 100.0)], 0.01),
    "RANDOM_1@5m": ("random", 5000.0, [], 0.0),
    "RANDOM_2@5m": ("random", 5000.0, [], 0.0),
    "RANDOM_3@5m": ("random", 4900.0, [(2, -100.0)], 0.02),
    "RANDOM_1@4h": ("random", 5000.0, [], 0.0),
    "S5_DONCHIAN_MFI_C1@15m": ("copy", 6000.0, [(7, 1000.0)], 0.0),
}


def _trade(c, aid, t, pnl, eq_after):
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
              "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (aid, "BTCUSDT", t - H, t, "SL" if pnl < 0 else "LOCK", 20, pnl, pnl / 100, eq_after,
               json.dumps({"side": 1, "entry_price": 100.0, "exit_price": 101.0, "fees": 0.1, "funding": 0.0})))


def make_db(path: str, world=WORLD) -> str:
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    engines = {}
    for aid, (kind, wallet, trades, mdd) in world.items():
        strat, tf = aid.split("@")
        c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)",
                  (aid, strat, tf, kind, START + (7 * DAY if kind == "copy" else 0), "paper-v4",
                   "S5_DONCHIAN_MFI" if kind == "copy" else None, "{}"))
        w = INIT
        for day, pnl in trades:
            w += pnl
            _trade(c, aid, START + day * DAY, pnl, w)
        engines[aid] = {"wallet": wallet, "bust": False, "max_drawdown": mdd,
                        "position": {"symbol": "BTCUSDT", "side": 1, "qty": 0.1, "entry_price": 100.0, "entry_time": NOW - H,
                                     "leverage": 20, "margin": 50.0, "stop_price": 99.0, "liq_price": 95.5,
                                     "tp_price": 102.0} if aid == "REEL_H1@5m" else None}
    # 5-minute-style equity samples for the drawdown inside the 7-day window (peak 5300, low 4770: 10 %)
    for ts, eq in ((START + 4 * DAY, 5100.0), (START + 5 * DAY, 5300.0), (START + 6 * DAY, 4770.0),
                   (START + 9 * DAY, 5250.0)):
        c.execute("INSERT INTO equity VALUES (?,?,?,?)", ("S5_DONCHIAN_MFI@15m", ts, eq, 0.0))
    c.execute("INSERT INTO state VALUES ('accounts', ?, ?)", (NOW, json.dumps({"engines": engines})))
    c.execute("INSERT INTO state VALUES ('run', ?, ?)", (START, json.dumps({"initial_equity": INIT, "taker_fee": 0.0005})))
    c.commit()
    c.close()
    return path


@pytest.fixture
def db(tmp_path):
    return make_db(str(tmp_path / "paper3.db"))


@pytest.fixture
def grid(db):
    return GR.Grid(Data(db))


def _client(db):
    app = create_app(db, hash_password(PW), b"s" * 32,
                     candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    c = TestClient(app)
    assert c.get("/api/v4/grid").status_code == 401                     # behind the same login
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c


def _cells(d):
    return {x["id"]: x for x in d["cells"]}


# ---------------------------------------------------------------- the map
def test_grid_cells_whole_run(grid):
    d = grid.grid(30, now_ms=NOW)
    assert d["covers_run"] is True and d["from"] == START and d["days"] == 30 and d["initial"] == INIT
    c = _cells(d)
    assert "S5_DONCHIAN_MFI_C1@15m" not in c                           # a copy started later: not on the map
    assert len(c) == len(WORLD) - 1
    s5 = c["S5_DONCHIAN_MFI@15m"]
    assert s5["g"] == "core" and s5["w0"] == INIT and s5["w"] == 5250.0
    assert s5["ret"] == pytest.approx(0.05) and s5["n"] == 3 and s5["win"] == 2 and s5["mdd"] == pytest.approx(0.12)
    # same-timeframe coin flips: 4900 / 5000 / 5100 -> median 0 %
    assert d["flips"]["15m"]["median"] == pytest.approx(0.0) and d["flips"]["15m"]["n"] == 3
    assert s5["vs"] == pytest.approx(0.05)
    assert c["S5_DONCHIAN_MFI@4h"]["vs"] == pytest.approx(-0.01)        # against the 4h flip, not the 15m ones
    # the reel against its three 5m flips (5000 / 5000 / 4900 -> 0 %)
    assert c["REEL_H1@5m"]["vs"] == pytest.approx(0.02) and c["REEL_H1@5m"]["open"] is True
    assert c["REEL_H1@5m"]["role"] == "reel_5m"
    # DeepSeek: no per-account comparison; its family and specialist role from paperbot/groups.py
    f9 = c["F9_FVG@15m"]
    assert f9["vs"] is None and f9["g"] == "ds200" and f9["fam"] == "F9" and f9["role"] == "ds_structure"
    assert c["F15_ASIA_BRK@15m"]["role"] == "ds_session"
    assert "F15_ASIA_BRK@4h" not in c                                  # a session definition has no 4h account
    assert c["RANDOM_1@15m"]["vs"] is None                             # a coin flip is the yardstick itself
    assert [r["key"] for r in d["roles"]][:4] == ["ds_structure", "ds_trend", "ds_session", "ds_reversal"]
    assert "F11_PO3" in next(r for r in d["roles"] if r["key"] == "ds_session")["defs"]
    assert d["judged"]["core"] == ["15m", "30m", "1h"] and "4h" in d["tfs"]["core"]
    assert d["min_color"] == GR.MIN_COLOR and d["small_n"] == GR.SMALL
    assert "참고" in d["basis_ko"] and "수수료" in d["basis_ko"]


def test_grid_seven_day_window_reads_the_balance_before_it(grid):
    d = grid.grid(7, now_ms=NOW)
    assert d["covers_run"] is False and d["from"] == NOW - 7 * DAY and d["days"] == 7
    c = _cells(d)
    s5 = c["S5_DONCHIAN_MFI@15m"]
    assert s5["w0"] == 5100.0 and s5["n"] == 2 and s5["win"] == 1     # the day-1 trade is before the window
    assert s5["ret"] == pytest.approx(5250 / 5100 - 1, abs=1e-6) and s5["mdd"] is None
    # flips in the window: 4900 -> 4900, 5000 -> 5000, 5000 -> 5100: median 0 %
    assert d["flips"]["15m"]["median"] == pytest.approx(0.0)
    assert s5["vs"] == pytest.approx(5250 / 5100 - 1, abs=1e-6)
    assert c["RANDOM_3@5m"]["w0"] == 4900.0 and c["RANDOM_3@5m"]["ret"] == pytest.approx(0.0)
    assert c["F9_FVG@15m"]["w0"] == INIT and c["F9_FVG@15m"]["n"] == 1      # its trade (day 4) is inside the window
    assert grid.grid("nonsense", now_ms=NOW)["days"] == 30 and grid.grid(90, now_ms=NOW)["days"] == 30


def test_sparks_sum_each_strategy(grid):
    d = grid.sparks(7, now_ms=NOW)
    assert len(d["t"]) == GR.SPARK_POINTS + 1 and d["t"][0] == NOW - 7 * DAY and d["t"][-1] == NOW
    s = d["strategies"]
    assert set(s) == {"S5_DONCHIAN_MFI", "F9_FVG", "F15_ASIA_BRK", "REEL_H1"}          # no flips, no copies
    s5 = s["S5_DONCHIAN_MFI"]
    assert s5["n"] == 2 and s5["w0"] == 5100.0 + 4950.0 and s5["v"][0] == pytest.approx(10050.0)
    assert s5["v"][-1] == pytest.approx(5250.0 + 4950.0) and s5["ret"] == pytest.approx(10200 / 10050 - 1, abs=1e-6)
    mid = s5["v"][len(d["t"]) // 2]                                     # day 6.5: after the day-5 loss only
    assert mid == pytest.approx(5050.0 + 4950.0)


# ---------------------------------------------------------------- the profile card
def test_account_profile(grid):
    p = grid.profile("S5_DONCHIAN_MFI@15m", 7, now_ms=NOW)
    assert p["kind"] == "account" and p["group"] == "core" and p["tf"] == "15m"
    assert p["ret"] == pytest.approx(5250 / 5100 - 1, abs=1e-6) and p["trades"] == 2 and p["win_rate"] == pytest.approx(0.5)
    assert p["mdd"] == pytest.approx(0.1)                               # from the samples inside the window
    v = p["spark"]["v"]
    assert len(v) == GR.PROFILE_POINTS + 1 and v[0] == 0.0 and v[-1] == pytest.approx(p["ret"], abs=1e-6)
    assert p["spark"]["flip"] is not None and len(p["spark"]["flip"]) == len(v)
    assert p["vs_basis"]["n"] == 3 and p["vs_basis"]["tf"] == "15m" and p["small_sample"] is True
    assert p["name_ko"]                                                 # the Telegram name of the 36
    whole = grid.profile("S5_DONCHIAN_MFI@15m", 30, now_ms=NOW)
    assert whole["mdd"] == pytest.approx(0.12)                         # the engine's own for the whole run
    assert whole["t"][0] == START


def test_deepseek_and_coin_flip_profiles(grid):
    ds = grid.profile("F9_FVG@15m", 30, now_ms=NOW)
    assert ds["vs"] is None and ds["spark"]["flip"] is None and "vs_basis" not in ds
    g = ds["ds_group"]
    assert g["n"] == 2 and g["median_ret"] == pytest.approx(-0.02) and g["flip_median_ret"] == pytest.approx(0.0)
    assert ds["family_ko"] and ds["role_ko"] == "구조·유동성 담당"
    reel = grid.profile("REEL_H1@5m", 30, now_ms=NOW)
    assert reel["vs_basis"]["ids"] == ["RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m"] and reel["vs"] == pytest.approx(0.02)
    flip = grid.profile("RANDOM_1@15m", 30, now_ms=NOW)
    assert flip["baseline"] is True and flip["vs"] is None and flip["spark"]["flip"] is None


def test_strategy_profile(grid):
    p = grid.profile("S5_DONCHIAN_MFI", 30, now_ms=NOW)
    assert p["kind"] == "strategy" and [a["tf"] for a in p["accounts"]] == ["15m", "4h"]
    c = p["combined"]
    assert c["w0"] == 10000.0 and c["w"] == pytest.approx(10200.0) and c["ret"] == pytest.approx(0.02)
    assert c["trades"] == 4 and c["wins"] == 2 and c["mdd_max"] == pytest.approx(0.12)
    assert c["above"] == 1 and c["below"] == 1 and c["vs_n"] == 2
    assert p["spark"]["v"][-1] == pytest.approx(0.02)
    ds = grid.profile("F15_ASIA_BRK", 30, now_ms=NOW)
    assert [a["tf"] for a in ds["accounts"]] == ["15m"] and ds["combined"]["vs_n"] == 0
    with pytest.raises(KeyError):
        grid.profile("NOPE", 30, now_ms=NOW)
    with pytest.raises(KeyError):
        grid.profile("S5_DONCHIAN_MFI_C1@15m", 30, now_ms=NOW)          # a copy is not on the map
    with pytest.raises(KeyError):
        grid.profile("RANDOM_1", 30, now_ms=NOW)                        # coin flips are not a strategy


# ---------------------------------------------------------------- routes, cache, cost
def test_routes_answer_and_never_write(db):
    before = hashlib.sha256(open(db, "rb").read()).hexdigest()
    c = _client(db)
    g = c.get("/api/v4/grid?days=7").json()
    assert g["days"] == 7 and len(g["cells"]) == len(WORLD) - 1
    s = c.get("/api/v4/grid/sparks?days=30").json()
    assert "S5_DONCHIAN_MFI" in s["strategies"]
    assert c.get("/api/v4/grid/profile/S5_DONCHIAN_MFI@15m?days=30").json()["kind"] == "account"
    assert c.get("/api/v4/grid/profile/S5_DONCHIAN_MFI").json()["kind"] == "strategy"
    r = c.get("/api/v4/grid/profile/NOPE")
    assert r.status_code == 404 and "없습니다" in r.json()["detail"]
    assert hashlib.sha256(open(db, "rb").read()).hexdigest() == before          # read-only


def test_cached_card_inside_cached_grid_does_not_deadlock(db):
    """A card asks for the cached grid while it holds the cache lock (the lock is re-entrant)."""
    g = GR.Grid(Data(db))
    out = {}
    t = threading.Thread(target=lambda: out.update(p=g.profile("S5_DONCHIAN_MFI@15m", 30), s=g.sparks(30)), daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive(), "profile / sparks deadlocked on the cache lock"
    assert out["p"]["kind"] == "account" and out["s"]["strategies"]
    assert g.grid(30) is g.grid(30)                                     # the cached answer is reused


def test_new_trades_are_read_incrementally(db, grid):
    first = _cells(grid.grid(7, now_ms=NOW))["S5_DONCHIAN_MFI@15m"]
    last_id = grid.trades.last_id
    c = sqlite3.connect(db)
    _trade(c, "S5_DONCHIAN_MFI@15m", NOW - H, 50.0, 5300.0)
    c.commit()
    c.close()
    again = _cells(grid.grid(7, now_ms=NOW))["S5_DONCHIAN_MFI@15m"]
    assert again["n"] == first["n"] + 1 and again["win"] == first["win"] + 1 and grid.trades.last_id == last_id + 1
    fresh = _cells(GR.Grid(Data(db)).grid(7, now_ms=NOW))["S5_DONCHIAN_MFI@15m"]
    assert (fresh["n"], fresh["win"], fresh["w0"]) == (again["n"], again["win"], again["w0"])


def test_empty_database(tmp_path):
    db = str(tmp_path / "empty.db")
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.close()
    g = GR.Grid(Data(db))
    d = g.grid(30, now_ms=NOW)
    assert d["cells"] == [] and d["flips"] == {} and d["covers_run"] is True
    assert g.sparks(7, now_ms=NOW)["strategies"] == {}
    with pytest.raises(KeyError):
        g.profile("S5_DONCHIAN_MFI@15m", 30, now_ms=NOW)
    cl = _client(db)
    assert cl.get("/api/v4/grid").json()["cells"] == []
    assert cl.get("/api/v4/grid/profile/S5_DONCHIAN_MFI@15m").status_code == 404


def test_answer_for_the_full_run_shape_stays_small(tmp_path):
    from paperbot.config import DS200_DEFS
    world = {}
    for s in [f"S{i}_X" for i in range(36)]:
        for tf in ("15m", "30m", "1h", "4h"):
            world[f"{s}@{tf}"] = ("strategy", 5000.0 + len(world), [(1, 10.0)], 0.01)
    for d, _f, tfs in DS200_DEFS:
        for tf in tfs:
            world[f"{d}@{tf}"] = ("ds200", 4990.0, [(2, -10.0)], 0.01)
    world["REEL_H1@5m"] = ("reel", 5000.0, [], 0.0)
    for tf in ("5m", "15m", "30m", "1h", "4h"):
        for k in (1, 2, 3):
            world[f"RANDOM_{k}@{tf}"] = ("random", 5000.0, [], 0.0)
    assert len(world) == 331
    db = make_db(str(tmp_path / "big.db"), world)
    g = GR.Grid(Data(db))
    d = g.grid(30, now_ms=NOW)
    assert len(d["cells"]) == 331 and len(json.dumps(d)) < 150_000
    assert sum(1 for x in d["cells"] if x["g"] == "ds200") == 171
    assert len(json.dumps(g.sparks(30, now_ms=NOW))) < 150_000


def test_small_sample_floor_is_the_checkpoint_one():
    from paperbot import checkpoint
    assert GR.SMALL == checkpoint.MIN_TRADES
    src = open(os.path.join(SCREENS, "grid-kit.js"), encoding="utf-8").read()
    assert f"export const SMALL = {checkpoint.MIN_TRADES};" in src and f"export const MIN_COLOR = {GR.MIN_COLOR};" in src


# ---------------------------------------------------------------- honesty in the page files
def _read(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as fh:
        return fh.read()


def test_page_files_keep_the_honesty_rules():
    kit, grid_js, css = _read("grid-kit.js"), _read("grid.js"), _read("grid-kit.css")
    # a coin-flip comparison never uses the up / down (pass / fail looking) colours: the neutral --cmp-hi / --cmp-lo
    # pair of tokens.css (classic: accent yellow / cyan; ai skin: yellow / blue), 참고
    base = re.search(r"\.gk-cell \{([^}]*)\}", css).group(1)
    assert "--hi: var(--cmp-hi)" in base and "--lo: var(--cmp-lo)" in base
    tokens = open(os.path.join(SCREENS, "..", "tokens.css"), encoding="utf-8").read()
    for blk in re.findall(r"(:root[^{]*)\{([^}]*)\}", tokens):
        for k in ("--cmp-hi", "--cmp-lo"):
            m = re.search(k + r":\s*([^;]+);", blk[1])
            assert m is None or not re.search(r"--up|--down", m.group(1)), (blk[0], k)
    assert re.search(r"\.own \.gk-cell, \.gk-cell\.own \{ --hi: var\(--up\); --lo: var\(--down\); \}", css)
    # DeepSeek is coloured by its own return, never by a per-account coin-flip difference
    assert 'group === "ds200" ? "own"' in grid_js or 'rowsOf(d, "ds200", "own")' in grid_js
    assert "계좌마다 동전 봇과 비교하지 않" in grid_js and "딥시크는 계좌마다 동전 봇과 비교하지 않" in kit
    for src in (kit, grid_js):
        assert "ui.refNote(" in src and "ui.assume(" in src
        assert not re.search(r"합격(?!·불합격)|통과|승자|우승", src.replace("합격·불합격", "")), "verdict words before day 30"
    # the account page and the strategies list use the kit; every closed trade row links to its replay
    acc, lst = _read("account.js"), _read("strategies-list.js")
    assert 'from "./grid-kit.js"' in acc and 'from "./grid-kit.js"' in lst
    assert 'ctx.href("replay", String(t.id))' in acc
    for css_name in ("grid.css", "account.css", "strategies.css"):
        assert '@import url("grid-kit.css");' in _read(css_name)
    # the map links to the existing analysis map instead of copying it
    assert 'ctx.href("analysis", "map")' in grid_js
