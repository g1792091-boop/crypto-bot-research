"""huntbot pieces (no network: a fake Binance answers; synthetic bars only):

- the public client: path whitelist, host, weights, 429 Retry-After, no key and no signed path anywhere in huntbot
- store: append-only bars, late bars counted, incremental reads
- feed: backfill paging, the settle rule (an unclosed kline is never stored), the completeness mark (held for a coin's
  missing bar and a due funding rate, released after the wait, never moved back), a coin leaving TRADING gets its end
- systems: the wide list + v1 aliases, cells, variants, the lineup file (checks, errors, suggestion)
- ledger: generations, idempotent events, actions become final
- D11: DeepSeek systems and lineup accounts carry no money in any served snapshot or Telegram text
- Telegram: entries / exits / adds of lineup accounts only, silence while catching up, one lineup message, the daily
  summary once
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from huntbot import binance as BN  # noqa: E402
from huntbot import config as CFG  # noqa: E402
from huntbot import feed as FD  # noqa: E402
from huntbot import notify as NT  # noqa: E402
from huntbot import snapshot as SN  # noqa: E402
from huntbot import systems as S  # noqa: E402
from huntbot.ledger import Ledger  # noqa: E402
from huntbot.store import Store  # noqa: E402

FIVE = CFG.FIVE
T0 = CFG.day_ms("2026-10-05")


# ---------------------------------------------------------------- a fake exchange
class FakeExchange:
    """Answers the whitelisted public endpoints from deterministic series; ``now`` decides what exists."""

    def __init__(self, syms, now_ms, start_ms=T0 - 3 * CFG.DAY):
        self.syms, self.now, self.start = list(syms), now_ms, start_ms
        self.status = {s: "TRADING" for s in syms}
        self.missing: dict = {}                       # sym -> set of open times the exchange does not have yet
        self.funding_delay: dict = {}                 # sym -> ms after the funding time before the rate shows
        self.calls: list = []

    def bar(self, sym, t):
        x = 100.0 + (hash((sym, t)) % 1000) / 100.0
        return [t, f"{x:.2f}", f"{x + 1:.2f}", f"{x - 1:.2f}", f"{x + 0.5:.2f}", "10.0", t + FIVE - 1, f"{1000 + x:.2f}",
                5, "1", "1", "0"]

    def fetch(self, url, headers, timeout):
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.calls.append((u.path, q))
        assert u.hostname == "fapi.binance.com" and "signature" not in q and "X-MBX-APIKEY" not in headers
        if u.path in ("/fapi/v1/klines", "/fapi/v1/markPriceKlines"):
            sym, t, lim = q["symbol"], int(q["startTime"]), int(q["limit"])
            t = max(t, self.start) // FIVE * FIVE + (FIVE if max(t, self.start) % FIVE else 0)
            rows = []
            while len(rows) < lim and t <= self.now:              # the open (unclosed) kline is included, as Binance
                if t not in self.missing.get(sym, set()):
                    rows.append(self.bar(sym, t))
                t += FIVE
            return 200, json.dumps(rows).encode(), {}
        if u.path == "/fapi/v1/fundingRate":
            sym, t = q["symbol"], int(q["startTime"])
            first = (max(t, self.start) // (8 * 3_600_000) + 1) * 8 * 3_600_000
            rows = [{"symbol": sym, "fundingTime": f + 3, "fundingRate": "0.0001"}
                    for f in range(first, self.now, 8 * 3_600_000) if f + 3 >= t
                    and f + self.funding_delay.get(sym, 0) <= self.now]
            return 200, json.dumps(rows[:int(q.get("limit", 1000))]).encode(), {}
        if u.path == "/fapi/v1/premiumIndex":
            nxt = (self.now // (8 * 3_600_000) + 1) * 8 * 3_600_000
            return 200, json.dumps([{"symbol": s, "nextFundingTime": nxt} for s in self.syms]).encode(), {}
        if u.path == "/fapi/v1/exchangeInfo":
            return 200, json.dumps({"symbols": [{"symbol": s, "status": st, "contractType": "PERPETUAL"}
                                                for s, st in self.status.items()]}).encode(), {}
        if u.path == "/fapi/v1/openInterest":
            return 200, json.dumps({"symbol": q["symbol"], "openInterest": "123.4", "time": self.now}).encode(), {}
        return 404, b"{}", {}


def make_feed(tmp_path, syms=("BTCUSDT", "ETHUSDT"), now=T0):
    ex = FakeExchange(syms, now)
    clock = [now / 1000]
    st = Store(str(tmp_path / "store.db"), clock=lambda: clock[0])
    cl = BN.Client(fetch=ex.fetch, sleep=lambda s: None)
    fd = FD.Feed(st, cl, list(syms), T0 - 2 * CFG.DAY, clock=lambda: clock[0], log=lambda m: None)
    return ex, st, fd, clock


# ---------------------------------------------------------------- client
def test_client_whitelist_weights_and_retry():
    calls = []

    def fetch(url, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            return 429, b"", {"Retry-After": "2"}
        return 200, b"[]", {}
    slept = []
    c = BN.Client(fetch=fetch, sleep=slept.append)
    assert c.klines("BTCUSDT", 0, 99) == []
    assert slept and slept[0] == 2.0 and len(calls) == 2
    with pytest.raises(ValueError):
        c.get("/fapi/v1/order", {"symbol": "BTCUSDT"})
    with pytest.raises(ValueError):
        c.get("/fapi/v2/account")
    assert BN.kline_weight(99) == 1 and BN.kline_weight(1000) == 5 and BN.kline_weight(1500) == 10
    c2 = BN.Client(fetch=lambda u, h, t: (500, b"", {}), sleep=lambda s: None, max_tries=3)
    with pytest.raises(BN.BinanceDown):
        c2.get("/fapi/v1/time")


def test_no_key_and_no_order_code_anywhere_in_huntbot():
    bad = re.compile(r"(API_KEY|api_secret|X-MBX-APIKEY|/fapi/v1/order|/fapi/v2/account|signature|hmac\.new\(secret, q)")
    for dp, _dn, fns in os.walk(os.path.join(ROOT, "huntbot")):
        for f in fns:
            if f.endswith((".py", ".js", ".html")):
                txt = open(os.path.join(dp, f), encoding="utf-8").read()
                hits = [m.group(0) for m in bad.finditer(txt)]
                assert not hits, (f, hits)


# ---------------------------------------------------------------- store and feed
def test_store_append_only_and_late_bars(tmp_path):
    st = Store(str(tmp_path / "s.db"))
    rows = [(T0 + i * FIVE, 1, 2, 0.5, 1.5, 10, 100) for i in range(5)]
    assert st.insert_bars("BTCUSDT", rows) == (5, 0)
    assert st.insert_bars("BTCUSDT", rows) == (0, 0)                      # first copy wins
    late = [(T0 - FIVE, 1, 2, 0.5, 1.5, 10, 100)]
    assert st.insert_bars("BTCUSDT", late) == (1, 1)
    st.commit()
    got = st.bars_since(0)["BTCUSDT"]
    assert [r[0] for r in got] == sorted(r[0] for r in rows + late)
    ins = st.max_ins()
    st.insert_bars("BTCUSDT", [(T0 + 5 * FIVE, 1, 2, 0.5, 1.5, 10, 100)])
    st.commit()
    assert [r[0] for r in st.bars_since(ins)["BTCUSDT"]] == [T0 + 5 * FIVE]
    assert any("late" in r["msg"] for r in st.recent_log())


def test_feed_backfill_settle_and_complete(tmp_path):
    now = T0 + 7 * FIVE + 5_000                          # 5 s after the 00:35 close: that kline is not final yet
    ex, st, fd, clock = make_feed(tmp_path, now=now)
    fd.backfill()
    last = st.max_open("BTCUSDT")
    assert last == T0 + 5 * FIVE                         # the 00:30 bar is stored, the 00:35 one (closes 00:35) is not
    assert st.complete_ms() == T0 + 6 * FIVE
    n_bars = st.conn.execute("SELECT COUNT(*) FROM bars_5m WHERE symbol = 'BTCUSDT'").fetchone()[0]
    assert n_bars == (last - (T0 - 2 * CFG.DAY)) // FIVE + 1           # paged from the warm-up start, no gap
    assert st.conn.execute("SELECT COUNT(*) FROM funding").fetchone()[0] > 0
    assert st.conn.execute("SELECT COUNT(*) FROM mark_5m").fetchone()[0] == 2 * n_bars
    # a coin missing its next bar holds the mark ...
    ex.now = T0 + 10 * FIVE + 20_000
    clock[0] = ex.now / 1000
    ex.missing["ETHUSDT"] = {T0 + 8 * FIVE, T0 + 9 * FIVE}
    fd.cycle()
    assert st.complete_ms() == T0 + 8 * FIVE
    # ... until it is stalled for longer than the wait; the mark never moves back
    ex.now = T0 + 20 * FIVE + 20_000
    clock[0] = ex.now / 1000
    ex.missing["ETHUSDT"] = {T0 + i * FIVE for i in range(7, 25)}
    fd.cycle()
    assert st.complete_ms() == T0 + 20 * FIVE
    assert st.get("stalled") == ["ETHUSDT"]


def test_feed_holds_the_mark_for_a_due_funding_rate(tmp_path):
    f8 = T0 + 8 * 3_600_000
    ex, st, fd, clock = make_feed(tmp_path, now=f8 - 3 * FIVE)
    fd.backfill()
    ex.funding_delay["BTCUSDT"] = 8 * 60_000                         # the 08:00 rate shows 8 minutes late
    ex.now = f8 + FIVE + 20_000
    clock[0] = ex.now / 1000
    fd.cycle()
    assert (st.coins()["BTCUSDT"]["expect_funding_ms"]) == f8
    assert st.complete_ms() == f8 - FIVE                             # the bar ending at 08:00 waits for its funding
    ex.now = f8 + 2 * FIVE + 20_000
    clock[0] = ex.now / 1000
    fd.cycle()
    assert st.coins()["BTCUSDT"]["expect_funding_ms"] is None
    assert st.complete_ms() == f8 + 2 * FIVE
    # a rate that never comes stops holding the mark after the wait
    f16 = f8 + 8 * 3_600_000
    ex.now = f16 - FIVE
    clock[0] = ex.now / 1000
    fd.cycle()
    ex.funding_delay["BTCUSDT"] = 10 ** 9
    for k in range(1, 5):
        ex.now = f16 + k * FIVE + 20_000
        clock[0] = ex.now / 1000
        fd.cycle()
    assert st.coins()["BTCUSDT"]["expect_funding_ms"] == f16 and st.complete_ms() == f16 + 4 * FIVE


def test_coin_leaving_trading_gets_its_end(tmp_path):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    fd.backfill()
    ex.status["ETHUSDT"] = "SETTLING"
    fd.refresh_exchange(force=True)
    c = st.coins()["ETHUSDT"]
    assert c["trading"] == 0 and c["end_ms"] == st.max_open("ETHUSDT")
    assert fd.trading() == ["BTCUSDT"]


def test_universe_formats(tmp_path):
    a = tmp_path / "u30.json"
    a.write_text(json.dumps({"symbols": ["BTCUSDT", "ETHUSDT"]}))
    b = tmp_path / "universe.json"
    b.write_text(json.dumps({"universe": ["BTCUSDT", "XRPUSDT"], "ranking": []}))
    assert CFG.load_universe(str(a))["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert CFG.load_universe(str(b))["symbols"] == ["BTCUSDT", "XRPUSDT"]
    with pytest.raises(ValueError):
        CFG.parse_universe({"symbols": ["BTCUSDT", "BTCUSDT"]})
    assert len(CFG.PREREG_UNIVERSE) == 30 and CFG.PREREG_UNIVERSE[:3] == ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def test_warmup_must_cover_400_days(monkeypatch):
    monkeypatch.setenv("HUNTBOT_WARMUP_START", "2026-01-01")
    with pytest.raises(ValueError):
        CFG.warmup_start_ms()
    monkeypatch.setenv("HUNTBOT_WARMUP_START", "2025-01-01")
    assert CFG.warmup_start_ms() == CFG.day_ms("2025-01-01")


# ---------------------------------------------------------------- systems and lineup
@pytest.fixture(scope="module")
def sysl():
    systems, aliases = S.system_list()
    return systems, aliases, {s["id"]: s for s in systems}


def test_system_list_and_cells(sysl):
    systems, aliases, by_id = sysl
    from research.hunt import entries_wide as EW
    assert len(systems) == len(EW.systems()) >= 730                 # v1's six are F1 G1 systems: aliases, not extra
    assert aliases["v1:E1:1h"] == "F1:E1:1h:G1" and len(aliases) == 6
    cells = S.cells_of(systems)
    assert len(cells) == len(systems) // 2 and all(len(c.systems) == 2 for c in cells.values())
    assert all(":G1" not in c and ":NONE" not in c for c in cells)
    assert S.cell_id(by_id["F1:E2:4h:NONE"]) == "F1:E2:4h"
    f4 = next(s for s in systems if s["family"] == "F4")
    assert S.cell_id(f4).startswith("F4:") and S.cell_id(f4).endswith(f":r{f4['rank']}")
    v = S.variants()
    assert v["goal2"]["risk_cap"] == pytest.approx(0.16) and v["goal5"]["b_div"] == pytest.approx(0.6)


def test_lineup_checks(sysl, tmp_path):
    systems, aliases, by_id = sysl
    ds = next(s["id"] for s in systems if s["kind"] == "ds")
    doc = {"accounts": [{"system": "v1:E2:4h", "label": "정식", "variant": "r0.5"},
                        {"system": ds, "label": "참고", "variant": "r1"},
                        {"basket": ["F1:E1:1h:NONE", "F1:E3:4h:G1"], "pick_nos": [1, 2], "label": "정식",
                         "variant": "r0.5"}]}
    acc = S.parse_lineup(doc, by_id, aliases)
    assert [a["id"] for a in acc] == ["F1:E2:4h:G1|r0.5", f"{ds}|r1", "basket:F1:E1:1h:NONE+F1:E3:4h:G1|r0.5"]
    assert [a["ds"] for a in acc] == [False, True, False] and acc[0]["alias"] == "v1:E2:4h"
    for bad in ({"accounts": [{"system": "F9:X", "label": "정식"}]}, {"accounts": [{"system": ds, "label": "본"}]},
                {"accounts": [{"system": ds, "label": "정식", "variant": "r9"}]},
                {"accounts": [{"system": ds, "label": "정식"}, {"system": ds, "label": "참고"}]}):
        with pytest.raises(S.LineupError):
            S.parse_lineup(bad, by_id, aliases)
    p = tmp_path / "lineup.json"
    p.write_text("{not json")
    assert S.read_lineup(str(p), by_id, aliases)["error"]
    with open(os.path.join(ROOT, "huntbot", "lineup.json")) as fh:
        assert S.parse_lineup(json.load(fh), by_id, aliases) == []                # empty at install


def test_suggest_lineup(tmp_path):
    out = tmp_path / "research" / "hunt" / "out"
    (out / "wide").mkdir(parents=True)
    (out / "v1").mkdir(parents=True)
    (out / "v1" / "pick.json").write_text(json.dumps({"pick": {"id": "v1:E1:4h"}, "label": "pick"}))
    (out / "v1" / "test.json").write_text(json.dumps({"verdict": {"v1_pass": False}}))
    (out / "wide" / "picks.json").write_text(json.dumps({"picks": [{"id": "F2:A:1h:G1", "pick_no": 1},
                                                                   {"id": "F2:B:4h:NONE", "pick_no": 2},
                                                                   {"id": "F3:C:1h:G1", "pick_no": 3}]}))
    (out / "wide" / "test.json").write_text(json.dumps({"verdict": {"passing": ["F2:A:1h:G1", "F2:B:4h:NONE"]}}))
    lu = S.suggest_lineup(str(tmp_path))
    by = [(a.get("system") or "basket", a["label"], a["variant"]) for a in lu["accounts"]]
    assert ("v1:E1:4h", "참고", "r0.5") in by and ("F2:A:1h:G1", "정식", "r1") in by
    assert ("F2:A:1h:G1", "참고", "goal5") in by and ("F3:C:1h:G1", "참고", "r0.5") in by
    assert ("basket", "정식", "r0.5") in by


# ---------------------------------------------------------------- ledger
def test_ledger_generations_and_actions(tmp_path):
    p = str(tmp_path / "events.db")
    led = Ledger(p, "hashA")
    row = {"cell": "F1:E1:1h", "tf": "1h", "symbol": "BTCUSDT", "side": "LONG", "bar_close_ms": T0, "sys_g1": "F1:E1:1h:G1",
           "sys_none": "F1:E1:1h:NONE", "regime_code": 1, "gated": 1}
    assert led.add_events([row]) == 1 and led.add_events([row]) == 0
    led.set_progress([("F1:E1:1h", "BTCUSDT", T0)])
    led.set_actions("F1:E1:1h", {("BTCUSDT", T0, "LONG"): ("PENDING_FILL", "PENDING_FILL")})
    led.commit()
    assert led.pending_since() == {"F1:E1:1h": T0}
    led.set_actions("F1:E1:1h", {("BTCUSDT", T0, "LONG"): ("OPENED", "BLOCKED_COIN_BUSY")})
    led.commit()
    assert led.pending_since() == {}
    v = led.conn.execute("SELECT system, rule_action, gated FROM events_systems ORDER BY gate").fetchall()
    assert v == [("F1:E1:1h:G1", "OPENED", 1), ("F1:E1:1h:NONE", "BLOCKED_COIN_BUSY", 1)]
    book = Ledger(p, "hashA").load_book()
    assert list(book[("F1:E1:1h", "BTCUSDT")]["long"]) == [T0]
    led2 = Ledger(p, "hashB")                                    # new signal code: a new generation, old rows kept
    assert led2.new_generation and led2.gen == 2 and led2.load_book() == {}
    assert led2.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    mode = led2.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


# ---------------------------------------------------------------- D11 and Telegram
class _R:
    """The parts of a Runner the snapshot and Telegram code read."""

    def __init__(self, tmp_path, accounts, systems):
        self.snap, self.private = str(tmp_path / "snap"), str(tmp_path / "private")
        self.fwd, self.done_ms = CFG.FORWARD_START_MS, T0
        self.lineup = {"accounts": accounts, "error": None}
        self.var = S.variants()
        self.systems = systems
        self.cell_of_sys = {s["id"]: S.cell_id(s) for s in systems}
        self.now = T0 + 60_000

    def now_ms(self):
        return self.now


def _trade(open_, pnl, coin="BTCUSDT", t=T0 - 3_600_000):
    return {"i": 0, "coin": coin, "side": 1, "pick_no": 0, "signal_close_ms": t - FIVE, "in_ms": t, "out_ms": t + 7200_000,
            "open": open_, "reason": "period_end_marked" if open_ else "stop", "stop_source": "chandelier",
            "p0": 100.0, "fill": 100.05, "d0": 2.0, "first_stop": 98.0, "q1": 12.5, "lev": 5, "u": 25.0, "eq_entry": 5000.0,
            "exit_px": 103.0, "adds": 2, "adds_tried": 2, "pnl": pnl, "price_pnl": pnl, "fees": 1.0, "funding": 0.0,
            "r_mult": pnl / 25.0, "large": 1, "cut": 0, "stop_now": {"stop": 101.0, "kind": "stop", "source": "chandelier"}
            if open_ else None}


def _res(trades):
    return {"summary": {"M": [1.01], "max_dd": 0.02, "bust": False, "fees": 3.0, "funding": 0.1, "day_eq": [5000, 5050],
                        "signal_counts": {"events": 5, "gated": 3}}, "equity_now": 5050.0, "bust_t": -1,
            "month_names": ["2026-10"], "trades": trades, "hourly": [5000.0, 5010.0]}


MONEY_KEYS = {"pnl", "price_pnl", "fill", "p0", "exit_px", "first_stop", "stop_now", "equity_now", "multiple",
              "max_dd", "months", "month_M", "hourly", "day_eq", "fees", "funding", "u", "eq_entry", "r_mult", "q1", "lev",
              "mean_pnl_U", "d0"}


def _walk_keys(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            out.add(k)
            _walk_keys(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_keys(v, out)
    return out


def test_deepseek_money_never_served_or_sent(tmp_path, sysl):
    systems, aliases, by_id = sysl
    ds = next(s for s in systems if s["kind"] == "ds")
    core = by_id["F1:E1:1h:NONE"]
    accts = S.parse_lineup({"accounts": [{"system": ds["id"], "label": "정식", "variant": "r0.5"},
                                         {"system": core["id"], "label": "참고", "variant": "r0.5"}]}, by_id, aliases)
    R = _R(tmp_path, accts, [ds, core])
    lres = {accts[0]["id"]: _res([_trade(True, 30.0), _trade(False, -20.0)]),
            accts[1]["id"]: _res([_trade(True, 30.0), _trade(False, 15.0)])}
    mk = type("M", (), {"start": CFG.FORWARD_START_MS, "months": ["2026-10"]})()
    SN.write_lineup(R, mk, T0, lres)
    SN.write_all(R, mk, T0, {ds["id"]: lres[accts[0]["id"]], core["id"]: lres[accts[1]["id"]]}, lres)
    lu = json.load(open(os.path.join(R.snap, "lineup.json")))
    dsa, ca = lu["accounts"]
    assert not (_walk_keys(dsa, set()) & MONEY_KEYS), _walk_keys(dsa, set()) & MONEY_KEYS
    assert {"equity_now", "pnl", "stop_now", "hourly"} <= _walk_keys(ca, set())
    rows = {r["id"]: r for r in json.load(open(os.path.join(R.snap, "systems.json")))["rows"]}
    assert not (_walk_keys(rows[ds["id"]], set()) & MONEY_KEYS)
    assert rows[ds["id"]]["closed"] == 1 and rows[ds["id"]]["wins"] == 0          # counts and win share stay
    for f in ("positions.json", "trades.json"):
        doc = json.load(open(os.path.join(R.snap, f)))
        ds_rows = [x for x in doc.get("rows", []) + doc.get("recent", []) if x.get("ds")]
        ds_rows += doc.get("by_system", {}).get(ds["id"], [])
        assert ds_rows and not (_walk_keys(ds_rows, set()) & MONEY_KEYS), f
    priv = json.load(open(os.path.join(R.private, "deepseek.json")))
    assert priv["systems"][0]["equity_now"] == 5050.0                               # the private file keeps it
    # Telegram: the DeepSeek account's texts carry no $, price or R
    a_ds = accts[0]
    for txt in (NT.entry_text(a_ds, _trade(True, 30.0), T0), NT.exit_text(a_ds, _trade(False, 25.0), T0),
                NT.add_text(a_ds, _trade(True, 30.0), 1, T0)):
        assert "$" not in txt and "100.05" not in txt and "R)" not in txt and "101" not in txt, txt
    assert "$" in NT.exit_text(accts[1], _trade(False, 25.0), T0)


def test_telegram_lineup_only_silent_catch_up_and_summary(tmp_path, sysl):
    systems, aliases, by_id = sysl
    from huntbot.runner import open_run_db
    conn = open_run_db(str(tmp_path / "run.db"))
    sent = []
    nt = NT.Notifier(conn, sender=sent.append)
    accts = S.parse_lineup({"accounts": [{"system": "F1:E1:1h:NONE", "label": "정식", "variant": "r0.5"}]}, by_id,
                           aliases)
    R = _R(tmp_path, accts, [by_id["F1:E1:1h:NONE"]])
    old = _trade(False, 10.0, t=T0 - 30 * 3_600_000)
    res = {accts[0]["id"]: _res([old])}
    out = nt.after_lineup(R, None, T0, res, caught_up=True)
    assert len(out) == 1 and out[0].startswith("📋 라인업")                   # the lineup message, the past not resent
    new = _trade(True, 5.0, coin="ETHUSDT", t=T0 - 10 * 60_000)
    res = {accts[0]["id"]: _res([old, new])}
    out = nt.after_lineup(R, None, T0, res, caught_up=True)
    assert [t.split("\n")[0] for t in out] == ["🟢 진입 · 추세 사냥", "➕ 추가 진입 1번째 · 추세 사냥", "➕ 추가 진입 2번째 · 추세 사냥"]
    closed = dict(new, open=False, reason="stop", out_ms=T0, pnl=40.0, r_mult=1.6)
    out = nt.after_lineup(R, None, T0, {accts[0]["id"]: _res([old, closed])}, caught_up=True)
    assert len(out) == 1 and out[0].startswith("✅ 청산") and "+$40.00" in out[0]
    assert nt.after_lineup(R, None, T0, {accts[0]["id"]: _res([old, closed])}, caught_up=True) == []
    # catching up: nothing is sent, but it is marked told
    late = _trade(True, 1.0, coin="SOLUSDT", t=T0 - 5 * 60_000)
    assert nt.after_lineup(R, None, T0, {accts[0]["id"]: _res([old, closed, late])}, caught_up=False) == []
    assert nt.after_lineup(R, None, T0, {accts[0]["id"]: _res([old, closed, late])}, caught_up=True) == []
    # the 09:00 KST summary once a day
    R.now = CFG.day_ms("2026-10-06") + 0 * 3_600_000 + 60_000              # 09:01 KST
    R.done_ms = R.now - 120_000
    out = nt.after_cycle(R, {}, caught_up=True)
    assert len(out) == 1 and out[0].startswith("📊 아침 요약") and "정식 1" in out[0]
    assert nt.after_cycle(R, {}, caught_up=True) == []
    assert all("disable_notification" not in t for t in sent) and len(sent) == 6
