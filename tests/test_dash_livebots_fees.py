"""실거래 › 비용 › 수수료 줄이기 (dash/more/livefees.py, sent as ``fees`` in GET /api/v4/livebots/costs; screens/livebots-cost.js),
owners 10/21 night: the 추세판단 봇's replay was about break-even before costs, the costs took ~4.5 %p a trade.

On a hand-made world (shared with tests/test_dash_livebots_goal_trend.py): the trend bot's paper database (trades booked as
the engine books them, one of the bot before it), 바이비트 (mainnet: two trades measured from their fills, one a wallet
estimate, one of the old bot) and WOO X Pro (mainnet: one measured, one whose cost the fills did not measure), each with its
equity samples:
- the fees from the fills (entry / exit), the slippage against the price the executor saw (entry_ref / exit_ref), before
  costs = net + fees + slippage - funding, per trade in net-ROE points, the shares (None without a profit before costs),
  the two spans (since the start / all, the old trade only in all), the counts left out (est / unmeasured), the maker case
  at Bybit's documented 0.02 % (entry only, both sides), WOO X Pro's maker 모름 (no number at all), the paper at its
  assumed rates (livereplayref.paper_row), the replay line; missing / unreadable databases say so;
- the documented rates are the repository's (docs/live1019-start-ko.md, docs/wooxpro-ko.md, docs/mexc-ko.md,
  docs/trade-review-system.md);
- the view in node (the tiny DOM): the words, no null / NaN, 모름 for an undocumented maker rate, the 가상 labels, the span
  switch remembered; the house rules of the css."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livefees as F  # noqa: E402
from paperbot.dash.more import livereplayref as X  # noqa: E402
from paperbot.executor import ExecStore  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
KST0 = 1_792_508_400_000                  # 2026-10-21 00:00 KST (a Wednesday)
SINCE = KST0 + 23 * HOUR + 28 * MIN       # the trend bot's start: 10/21 23:28 KST
NOW = KST0 + 6 * DAY + 12 * HOUR          # 10/27 (Tuesday) 12:00 KST
SLIP, FEE = 0.0002, 0.0005                # the paper rules' slippage and taker fee a side
ACC = L.ACCOUNT
BYBIT_TAKER = 0.00055
WOO_TAKER = 0.00042
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")
CFG = {"name": "추세판단 봇", "trend": {"vote_min": 3, "time_bars": None}, "leverage": {"BTCUSDT": 40, "default": 30}, "margin": 0.4,
       "initial_equity": 1000, "stop": {"mode": "roe", "roe": 0.5, "net": True},
       "ladder": {"first_lock": 0.1, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03},
       "members": [{"strategy": "F9_FVG", "tf": "1h", "no_chase": True}, {"strategy": "N20_EMA9_CHOP", "tf": "30m", "no_chase": True}]}


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


# ================================================================ the world
def _paper_trade(conn, sym, side, et, xt, reason, e_raw, x_raw, strategy, tf, lev, eq, margin=400.0):
    """A closed paper trade as the engine books it: fills with the slippage against, the taker fee both ways."""
    fill = e_raw * (1 + side * SLIP)
    xfill = x_raw * (1 - side * SLIP)
    qty = margin * lev / fill
    fees = qty * fill * FEE + qty * xfill * FEE
    pnl = side * qty * (xfill - fill) - fees
    d = {"strategy_id": strategy, "symbol": sym, "timeframe": tf, "side": side, "entry_time": et, "entry_price": fill,
         "exit_time": xt, "exit_price": xfill, "exit_reason": reason, "qty": qty, "leverage": lev, "margin": margin, "fees": fees,
         "funding": 0.0, "pnl": pnl, "roe": pnl / margin, "context": {}}
    conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", (ACC, sym, et, xt, reason, lev, pnl, pnl / margin, eq + pnl, json.dumps(d)))
    return d


# (coin, side, entry ms, hours held, reason, raw entry, raw exit, member, timeframe, leverage)
PAPER = (("BTCUSDT", 1, KST0 + DAY + 10 * HOUR, 1, "LOCK", 60000.0, 60450.0, "F9_FVG", "1h", 40),
         ("ETHUSDT", -1, KST0 + DAY + 15 * HOUR, 2, "SL", 2500.0, 2541.0, "N20_EMA9_CHOP", "30m", 30),
         ("SOLUSDT", 1, KST0 + 2 * DAY + 11 * HOUR, 1, "JUDGE", 150.0, 149.8, "F9_FVG", "1h", 30),
         ("DOGEUSDT", -1, KST0 + 5 * DAY + 10 * HOUR, 1, "LOCK", 0.2, 0.1985, "N20_EMA9_CHOP", "30m", 30))
OLD = ("LTCUSDT", 1, KST0 + 20 * HOUR, 1, "LOCK", 80.0, 80.5, "F3_BOS", "30m", 30)          # the bot before (10/21 20:00 KST)


def _paper_world(path):
    s = Store3(path)
    s.put_state("combo_run", SINCE, {"taker_fee": FEE, "config": CFG})
    s.put_state("trend", NOW, {"since": SINCE})
    eq, out = 1000.0, []
    for sym, side, et, held, reason, e, x, strat, tf, lev in (OLD,) + PAPER:
        d = _paper_trade(s.conn, sym, side, et, et + held * HOUR, reason, e, x, strat, tf, lev, eq)
        eq += d["pnl"]
        out.append(d)
    s.put_state("accounts", NOW - MIN, {"engines": {ACC: {"wallet": eq, "position": None}}})
    s.close()
    return out[0], out[1:], eq


def _live(st, pt, taker, *, cost=True, ok=True, funding=0.0, fid=0):
    """An executor's close of the paper trade ``pt`` (margin $10): its fills (entry 0.03 % worse than the paper's, the
    exit 0.01 % worse), the prices it saw (entry_ref 0.02 % better than its fill, exit_ref 0.02 % better), its costs as
    executor.py books them (trade_costs) when ``cost``. Returns what the page must show."""
    side, lev, sym = pt["side"], pt["leverage"], pt["symbol"]
    e = pt["entry_price"] * (1 + side * 0.0003)
    x = pt["exit_price"] * (1 - side * 0.0001)
    e_ref, x_ref = e / (1 + side * 0.0002), x * (1 + side * 0.0002)
    qty = 10.0 * lev / e
    key = f"{ACC}|{sym}|{pt['entry_time']}"
    t = {"key": key, "symbol": sym, "side": side, "qty": qty, "leverage": lev, "entry_ts": pt["entry_time"] + 3000, "entry_price": e,
         "stop_initial": e * (1 - side * 0.0125), "stop": e * (1 - side * 0.0125), "mode": "mainnet", "entry_time": pt["entry_time"],
         "paper_entry": pt["entry_price"], "entry_ref": e_ref, "exit_ref": x_ref}
    st.trade_open(t)
    fee_in, fee_out = qty * e * taker, qty * x * taker
    realized = side * qty * (x - e)
    pnl = realized - fee_in - fee_out + funding
    slip_in, slip_out = qty * side * (e - e_ref), qty * side * (x_ref - x)
    st.trade_close(key, pt["exit_time"] + 2000, "paper 청산 → 거래소 포지션 닫기", pnl, t, "fills" if cost else "wallet")
    open_side, close_side = ("BUY", "SELL") if side > 0 else ("SELL", "BUY")
    if cost:
        st.fills(key, [{"symbol": sym, "id": fid + 1, "side": open_side, "qty": qty, "price": e, "commission": fee_in, "commissionAsset": "USDT",
                        "time": pt["entry_time"] + 3000, "realizedPnl": 0.0},
                       {"symbol": sym, "id": fid + 2, "side": close_side, "qty": qty, "price": x, "commission": fee_out, "commissionAsset": "USDT",
                        "time": pt["exit_time"] + 2000, "realizedPnl": realized}])
        st.trade_costs(key, {"pnl": pnl, "realized": realized, "commission": fee_in + fee_out, "funding": funding,
                             "slippage": slip_in + slip_out, "real_cost": fee_in + fee_out + slip_in + slip_out,
                             "assumed_cost": 2 * qty * e * (FEE + SLIP), "ok": ok})
    m = e * qty / lev
    return {"key": key, "pnl": pnl, "fee_in": fee_in, "fee_out": fee_out, "slip_in": slip_in, "slip_out": slip_out, "funding": funding,
            "margin": m, "n_in": qty * e, "n_out": qty * x, "before": pnl + fee_in + fee_out + slip_in + slip_out - funding}


def _exec_world(path, cfg_path, paper_path, exchange, rows, equity):
    st = ExecStore(path, lock=False)
    st.put_state("bot", NOW - 5000, {"mode": "mainnet", "risk": {"last_equity": equity[-1][1]}})
    st.put_state("meta", KST0 - 10 * DAY, {"mode": "mainnet", "account": ACC, "exchange": exchange})
    out = [_live(st, *r[:2], **r[2]) for r in rows]
    for ts, eq in equity:
        st.equity(ts, eq, eq, 0.0)
    st.close()
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump({"account": ACC, "paper_db": paper_path, "db": path, "exchange": exchange, "mode": "mainnet", "qty_scale": 0.025}, fh)
    return out


def build_world(tmp) -> dict:
    """Every file of the world in the folder ``tmp`` (a pathlib.Path); the paths, the expected costs, the fees answer."""
    paper = str(tmp / "live-ac.db")
    old, pts, wallet = _paper_world(paper)
    p = {"paper": paper, "paper2": str(tmp / "none-paper2.db"), "bybit_db": str(tmp / "bybit.db"), "mexc_db": str(tmp / "woo.db"),
         "bybit_config": str(tmp / "executor.json"), "mexc_config": str(tmp / "executor-mexc.json")}
    by = _exec_world(p["bybit_db"], p["bybit_config"], paper, "bybit",
                     [(old, BYBIT_TAKER, {"fid": 10}), (pts[0], BYBIT_TAKER, {"fid": 20, "funding": -0.01}),
                      (pts[1], BYBIT_TAKER, {"fid": 30}), (pts[2], BYBIT_TAKER, {"cost": False})],
                     [(KST0 - 20 * DAY, 100.0), (KST0 + 12 * HOUR, 104.0), (NOW - HOUR, 98.8)])
    woo = _exec_world(p["mexc_db"], p["mexc_config"], paper, "wooxpro",
                      [(pts[0], WOO_TAKER, {"fid": 40}), (pts[3], WOO_TAKER, {"fid": 50, "ok": False})],
                      [(KST0 + 22 * HOUR, 100.0), (NOW - HOUR, 101.2)])
    no = str(tmp / "none")
    more = {**L.paths_more(), "combo_config": "/nonexistent/combo.json", "check_db": no + "-check.db", "improve_db": no + "-imp.db",
            "rule_db": no + "-rule.db", "shadow_dir": no}
    L._cache.clear()
    f = json_finite(F.fees(p, NOW))
    return {"p": p, "more": more, "old": old, "pts": pts, "wallet": wallet, "by": by, "woo": woo, "f": f, "tmp": tmp}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("fees"))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    yield
    L._cache.clear()


# ================================================================ the documented rates
def test_the_rates_are_the_repositorys_documented_ones():
    r = F.RATES
    assert (r["bybit"]["taker"], r["bybit"]["maker"]) == (0.00055, 0.0002) and r["bybit"]["src"] == "docs/live1019-start-ko.md"
    assert "테이커 0.055%, 메이커 0.02%" in _read(ROOT, r["bybit"]["src"])
    # WOO X Pro: the taker is documented (0.06 %, 0.042 % after TetherMax), the maker is not: None (모름), never guessed
    assert (r["wooxpro"]["taker"], r["wooxpro"]["taker_disc"], r["wooxpro"]["maker"]) == (0.0006, 0.00042, None)
    woo_doc = _read(ROOT, r["wooxpro"]["src"])
    assert "0.042%" in woo_doc and "0.06%" in woo_doc and not re.search(r"메이커\s*\d", woo_doc) and "maker" not in woo_doc.lower()
    assert (r["mexc"]["taker"], r["mexc"]["maker"]) == (0.0008, 0.0006) and "메이커 0.06%, 테이커 0.08%" in _read(ROOT, r["mexc"]["src"])
    assert (r["binance"]["taker"], r["binance"]["maker"]) == (0.0005, 0.0002) and "메이커 0.02%, 테이커 0.05%" in _read(ROOT, r["binance"]["src"])
    assert F.rates_of("nowhere")["maker"] is None and F.rates_of(None)["taker"] is None
    assert F.RATES_KO == "기본 등급 요율 · 두 분 계정 등급에 따라 다를 수 있어요"


# ================================================================ 수수료 줄이기 (server)
def test_fees_per_trade_and_per_span(world):
    f, by = world["f"], world["by"]
    assert f["state"] == "ok" and f["since"] == SINCE and f["trend"]["name"] == "추세판단 봇" and f["not_trend_ko"] is None
    ex = {x["id"]: x for x in f["execs"]}
    b = ex["bybit"]
    assert (b["state"], b["exchange"], b["real"], b["name_ko"]) == ("ok", "bybit", True, "바이비트")
    assert b["rates"]["maker"] == 0.0002
    # all of its trades: the old bot's too (measured), the wallet estimate counted and left out of the sums
    a = b["all"]
    assert (a["n"], a["measured"], a["est"], a["unmeasured"]) == (4, 3, 1, 0)
    # since the start: the old trade is not in it
    s = b["since"]
    assert (s["n"], s["measured"], s["est"]) == (3, 2, 1) and s["small"] is True
    exp = by[1:3]
    assert s["fee"] == pytest.approx(sum(t["fee_in"] + t["fee_out"] for t in exp))
    assert s["fee_in"] == pytest.approx(sum(t["fee_in"] for t in exp)) and s["fee_out"] == pytest.approx(sum(t["fee_out"] for t in exp))
    assert s["slip_in"] == pytest.approx(sum(t["slip_in"] for t in exp)) and s["slip_out"] == pytest.approx(sum(t["slip_out"] for t in exp))
    assert s["slip"] == pytest.approx(s["slip_in"] + s["slip_out"]) and s["slip"] > 0
    assert s["before"] == pytest.approx(sum(t["before"] for t in exp)) and s["pnl"] == pytest.approx(sum(t["pnl"] for t in exp))
    assert s["before"] - s["fee"] - s["slip"] + s["funding"] == pytest.approx(s["pnl"])
    assert s["fee_rate"] == pytest.approx(BYBIT_TAKER)                       # the rate really paid a side
    assert s["fee_roe"] == pytest.approx(sum((t["fee_in"] + t["fee_out"]) / t["margin"] for t in exp) / 2)
    assert s["before_roe"] - s["fee_roe"] - s["slip_roe"] + s["funding_roe"] == pytest.approx(s["net_roe"])
    # the share of the before-cost profit: there was one here (the BTC lock beat the ETH stop? no: the sum decides)
    if s["before"] > 0:
        assert s["fee_share"] == pytest.approx(s["fee"] / s["before"]) and s["slip_share"] == pytest.approx(s["slip"] / s["before"])
    else:
        assert s["fee_share"] is None and s["slip_share"] is None
    rows = {r["key"]: r for r in s["rows"]}
    btc = rows[exp[0]["key"]]
    assert btc["measured"] and btc["fee_in"] == pytest.approx(exp[0]["fee_in"]) and btc["fee_out"] == pytest.approx(exp[0]["fee_out"])
    assert btc["slip_in"] == pytest.approx(exp[0]["slip_in"]) and btc["funding"] == pytest.approx(-0.01)
    assert btc["before"] == pytest.approx(exp[0]["before"]) and btc["fee_roe"] == pytest.approx((exp[0]["fee_in"] + exp[0]["fee_out"]) / exp[0]["margin"])
    est = next(r for r in s["rows"] if not r["measured"])
    assert est["why"] == "est" and est["fee"] is None and est["before"] is None and est["slip"] is None   # never a 0
    assert [r["exit_time"] for r in s["rows"]] == sorted((r["exit_time"] for r in s["rows"]), reverse=True)


def test_fees_the_maker_case_and_an_unknown_maker(world):
    f, by, woo = world["f"], world["by"], world["woo"]
    ex = {x["id"]: x for x in f["execs"]}
    s = ex["bybit"]["since"]
    exp = by[1:3]
    mi, mb = s["maker_in"], s["maker_both"]
    save_in = sum(t["fee_in"] - t["n_in"] * 0.0002 for t in exp)
    save_both = sum(t["fee_in"] + t["fee_out"] - (t["n_in"] + t["n_out"]) * 0.0002 for t in exp)
    assert mi["n"] == mb["n"] == 2 and mi["save"] == pytest.approx(save_in) and mb["save"] == pytest.approx(save_both)
    assert mi["fee"] == pytest.approx(s["fee"] - save_in) and mi["pnl"] == pytest.approx(s["pnl"] + save_in)
    assert mi["pnl_paid"] == pytest.approx(s["pnl"]) and 0 < mi["save"] < mb["save"] < s["fee"]
    assert mi["save_roe"] == pytest.approx(sum((t["fee_in"] - t["n_in"] * 0.0002) / t["margin"] for t in exp) / 2)
    # WOO X Pro: no documented maker rate -> no maker number at all, its fees still measured
    w = ex["mexc"]
    assert (w["exchange"], w["name_ko"], w["rates"]["maker"]) == ("wooxpro", "WOO X Pro", None)
    ws = w["since"]
    assert (ws["n"], ws["measured"], ws["unmeasured"]) == (2, 1, 1)               # cost_ok 0: its fills did not measure the cost
    assert ws["fee"] == pytest.approx(woo[0]["fee_in"] + woo[0]["fee_out"]) and ws["fee_rate"] == pytest.approx(WOO_TAKER)
    assert ws["maker_in"] is None and ws["maker_both"] is None
    assert all(r["maker_in"] is None for r in ws["rows"])
    un = next(r for r in ws["rows"] if not r["measured"])
    assert un["why"] == "unmeasured" and un["fills"] == 2 and un["fee"] is None


def test_fees_the_paper_and_the_replay(world):
    f, pts = world["f"], world["pts"]
    pa = f["paper"]
    rows = [X.paper_row(t, SLIP) for t in pts]
    assert pa["state"] == "ok" and pa["n"] == pa["measured"] == 4 and pa["taker"] == FEE and pa["slip_rate"] == SLIP
    assert pa["fee_roe"] == pytest.approx(sum(r["fee"] for r in rows) / 4) and pa["slip_roe"] == pytest.approx(sum(r["slip"] for r in rows) / 4)
    assert pa["before_roe"] == pytest.approx(sum(r["before"] for r in rows) / 4)
    assert pa["fee"] == pytest.approx(sum(t["fees"] for t in pts)) and pa["slip"] == pytest.approx(sum(r["slip"] * 400.0 for r in rows))
    assert pa["note_ko"] == F.PAPER_KO
    rp = f["replay"]
    assert rp["state"] == "ok" and (rp["n"], rp["before"], rp["slip"], rp["fee"], rp["net"]) == (89, -0.0044, 0.0128, 0.032, -0.0492)
    assert rp["cost"] == pytest.approx(0.0448) and rp["lev_mean"] == pytest.approx(32.02)
    for k in ("limit_ko", "exit_ko", "who_ko", "rates_ko"):
        assert f[k]
    assert "안 채워질 수 있어요" in f["limit_ko"] and "두 분이 정해요" in f["who_ko"] and "아무것도 바꾸지 않아요" in f["who_ko"]


def test_fees_in_the_costs_answer_and_honest_states(world, tmp_path):
    co = L.costs(world["p"], NOW)
    assert co["fees"]["state"] == "ok" and {x["id"] for x in co["fees"]["execs"]} == {"bybit", "mexc"}
    p = dict(world["p"], mexc_db=str(tmp_path / "gone.db"))
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database at all" * 50)
    p["bybit_db"] = str(bad)
    f = F.fees(p, NOW)
    ex = {x["id"]: x for x in f["execs"]}
    assert ex["mexc"]["state"] == "missing" and ex["mexc"]["reason_ko"] and "since" not in ex["mexc"]
    assert ex["bybit"]["state"] == "error" and ex["bybit"]["reason_ko"]
    assert F.read_extra(str(tmp_path / "nothing.db"))["state"] == "missing"
    # another bot (no trend in its start record): all of its trades only, said so
    other = str(tmp_path / "other.db")
    s = Store3(other)
    s.put_state("combo_run", SINCE, {"taker_fee": FEE, "config": {**CFG, "trend": None, "name": "규칙봇 15"}})
    s.close()
    g = F.fees(dict(world["p"], paper=other), NOW)
    assert g["since"] is None and g["trend"] is None and g["not_trend_ko"] == F.NOT_TREND_KO
    assert all(x.get("since") is None for x in g["execs"] if x["state"] == "ok")
    # the read is read-only (a query_only connection)
    with sqlite3.connect(world["p"]["bybit_db"]) as c:
        n = c.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    assert n == 6


def test_split_fills_and_a_commission_in_another_asset():
    f = [{"side": "BUY", "qty": 1, "price": 100, "commission": 0.05, "commissionAsset": "USDT"},
         {"side": "SELL", "qty": 1, "price": 101, "commission": 0.01, "commissionAsset": "BNB"}]
    sp = F.split_fills(1, f)
    assert sp["fee_in"] == pytest.approx(0.05) and sp["fee_out"] is None and sp["avg_out"] == 101 and sp["n_in"] == 100
    sh = F.split_fills(-1, f)                                                  # a short opens with the SELL
    assert sh["fee_in"] is None and sh["fee_out"] == pytest.approx(0.05)
    assert F.split_fills(1, [])["fee_in"] is None


# ================================================================ the views in node
def _node(tmp_path, body: str, **data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              f"const K = await import('file://{SCREENS}/livebots-cost.js'); const G = await import('file://{SCREENS}/livebots-goal.js');\n"
              + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (a) => ({params: {query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, href: (n) => '#/' + n,"
              " every() {}, api: async () => JSON.parse(JSON.stringify(a))});\n"
              "const run = async (V, a) => { const v = V(mkCtx(a)); await tick(); await tick(); return v; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_cost_view_draws_the_fees(world, tmp_path):
    co = L.costs(world["p"], NOW)
    out = _node(tmp_path, """const v = await run(K.costView, D_co); const t1 = texts(v.el);
    localStorage.setItem('pb4-lbk-fee-span', JSON.stringify('all'));            // the switch remembered on "전체 거래"
    const t2 = texts((await run(K.costView, D_co)).el);
    const f = D_co.fees, by = f.execs.find((x) => x.id === 'bybit'), woo = f.execs.find((x) => x.id === 'mexc');
    console.log(JSON.stringify({t1, t2,
      pts: [K.ptsKo(0.032), K.ptsKo(-0.001), K.ptsKo(null)], rate: [K.rateKo(0.00055), K.rateKo(0.0002), K.rateKo(0.0006), K.rateKo(0.001), K.rateKo(null)],
      share: [K.shareWords(10, 2, 1), K.shareWords(10, 8, 4), K.shareWords(-1, 2, 1), K.shareWords(null, 2, 1), K.shareWords(5, null, 1)],
      span: [K.spanOf(f, 'since'), K.spanOf(f, 'all'), K.spanOf({since: null}, 'since')],
      tiles: K.feeTiles(by.since).map((x) => [x.id, x.v]), tiles0: K.feeTiles({measured: 0}).length,
      mk: K.makerLines(by.since, by.rates), mkw: K.makerLines(woo.since, woo.rates), pt: K.paperFeeTiles(f.paper).map((x) => [x.id, x.v]),
      rr: K.rateRows(f), rp: K.replayFeeKo(f.replay), rp0: K.replayFeeKo({state: 'missing'})}));""", co=co)
    t = out["t1"]
    for w in ("수수료 줄이기", "추세판단 봇 시작부터 (10/21 23:28) 닫힌 거래", "낸 수수료", "미끄러짐", "거래당 순ROE", "비용이 가져간 몫",
              "지정가(메이커)로 들어갔다면", "가상", "진입만 지정가 (메이커 0.02%)", "청산까지 지정가 (최대치)",
              "메이커 요율 모름", "drill 결과의 maker_pct로 확인", "체결로 비용을 잰 거래", "지갑 변화로 어림한 거래 1번",
              "비용을 못 잰 거래 1번", "거래마다 (새것부터, 순ROE)", "체결 기록 전 · 지갑 변화로 어림한 거래라 비용을 못 나눠요",
              "페이퍼(연습)", "모의 · 가정 요율", "수수료 (가정)", "테이커 0.05% 양쪽", "거래소 요율 (한쪽)", "테이커 0.055%", "메이커 0.02%",
              "테이커 0.06% (할인 0.042%)", "메이커 모름", "docs/live1019-start-ko.md", "docs/wooxpro-ko.md",
              "기본 등급 요율 · 두 분 계정 등급에 따라 다를 수 있어요", "지정가 주문은 안 채워질 수 있어요", "그 위험(놓친 이익·피한 손실)은 이 숫자에",
              "실행기를 지정가로 바꿀지는 두 분이 정해요", "재현(7/1~10/20, 가상): 비용 전 거래당 −0.4%", "수수료 3.2%p", "미끄러짐 1.3%p",
              "평균 32배", "표본 적음"):
        assert w in t, w
    assert not BAD.search(t), BAD.search(t)
    assert "전체 거래 (전환 전 포함)" in out["t2"] and "추세판단 봇 시작부터 (10/21" not in out["t2"] and not BAD.search(out["t2"])
    assert out["pts"] == ["3.2%p", "−0.1%p", "—"] and out["rate"] == ["0.055%", "0.02%", "0.06%", "0.1%", "모름"]
    assert out["share"][0] == "비용 전 이익의 20%는 수수료 · 10%는 미끄러짐" and out["share"][1].startswith("비용이 비용 전 이익의 120%")
    assert out["share"][2] == "비용 전에도 손실 · 비용이 손실을 더 키움" and out["share"][3] == out["share"][4] == "비용 못 잼"
    assert out["span"] == ["since", "all", "all"]
    tiles = dict(out["tiles"])
    assert tiles["fee"].endswith(" USDT") and " → " in tiles["per"] and out["tiles0"] == 0
    assert out["mk"]["known"] and [x["id"] for x in out["mk"]["lines"]] == ["in", "both"] and out["mk"]["lines"][0]["v"].startswith("+")
    assert out["mkw"]["known"] is False and out["mkw"]["lines"] == [] and out["mkw"]["ko"].startswith("메이커 요율 모름")
    assert [x[0] for x in out["pt"]] == ["per", "fee", "slip", "share"]
    assert [r["maker"] for r in out["rr"]] == ["메이커 0.02%", "메이커 모름"]
    assert out["rp"].startswith("재현(7/1~10/20, 가상)") and out["rp0"] is None


def house_rules(name: str, pre: str) -> None:
    """A screen's css: tokens only, every font size a token, every selector the screen's own prefix; its js: node --check."""
    css = re.sub(r"/\*.*?\*/", "", _read(SCREENS, f"{name}.css"), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\b(rgba?|hsla?)\(\s*\d", css), name
    assert not re.search(r"font-size:\s*\d", css) and not re.search(r"font:\s*[^;]*\d+px", css), name
    for sel in re.findall(r"(?:^|})\s*([^{}@]+?)\s*{", css):
        for part in sel.split(","):
            part = part.strip()
            if part and not part.startswith(("from", "to")) and not re.match(r"^\d", part):
                assert re.search(r"\." + pre + r"(-|\b)", part), (name, part)
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", os.path.join(SCREENS, f"{name}.js")], capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stderr)


def test_the_files_keep_the_house_rules():
    house_rules("livebots-cost", "lbk")
    assert "수수료 줄이기" in _read(ROOT, "docs", "livedash-ko.md") and "수수료 줄이기" in _read(ROOT, "paperbot", "dash", "static", "v4", "INVENTORY.md")

