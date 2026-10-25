"""The fifth live executor, 투비트 (owners 10-25, docs/toobit-ko.md: a $50 executor on Toobit following the rule bot's
V3.9 1-hour account ``V39_ALL@1h`` in paper3.db, chosen 10-25 night) as an optional
slot of the live checks, the Telegram messages and the live site, the way WOO X Pro 2 was added
(tests/test_wooxpro2_slot.py).

Invisible until installed (its config /etc/paperbot/executor-toobit.json or its database
/var/lib/paperbot/exec/executor-toobit-live.db is there): with the slot's keys but no file every site answer is the one
without the keys, with two executors and with four, and the checks read the executors they read before. Once installed:
checked, told and scored by its own name (투비트, from its config's exchange), its assumed fee 0.06 % a side.

The five-executor world: tests/test_wooxpro2_slot.py's four (바이비트 and WOO X Pro on the 추세판단 봇, 딥코인 on vwap.db,
WOO X Pro 2 on a hand-made '친구 매매법') plus 투비트 on a hand-made rule-bot paper file (paper3.db, account V39_ALL@1h,
no bot name in it): it pairs its trades with that account, names it by the account, and never takes the second paper
bot's place.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot import executor as E  # noqa: E402
from paperbot import livecheck as LC  # noqa: E402
from paperbot import liveteam as T  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livefees as F  # noqa: E402
from paperbot.dash.more import livepos as LPOS  # noqa: E402
from paperbot.dash.more import livetape as LT  # noqa: E402
from paperbot.executor import ExecStore  # noqa: E402
from paperbot.notify import INFO, ListNotifier  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402
from tests import test_livecheck as TL  # noqa: E402
from tests import test_wooxpro2_slot as W2  # noqa: E402
from tests import vwap_site_world as V  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "executor.live-toobit.json"
NOW, MIN, H, DAY = V.NOW, V.MIN, V.H, V.DAY
SCREENS, BAD = FW.SCREENS, FW.BAD
TB_ACC = "V39_ALL@1h"                       # the rule bot's V3.9 1-hour paper account (the template's, docs/toobit-ko.md)
TB_TAKER = 0.0006                           # Toobit's base taker fee a side
# (coin, side, entry ms, hours held, reason, raw entry, raw exit): R1 a win, R2 a stop, both followed by 투비트
RULE = (("BTCUSDT", 1, V.K(5, 9), 3, "LOCK", 61000.0, 61500.0),
        ("ETHUSDT", -1, V.K(5, 18), 2, "SL", 2450.0, 2480.0))
RPOS = ("DOGEUSDT", 1, V.K(6, 10), 0.21)    # the open one: 투비트 holds it too
WRONG_JOSA = re.compile(r"투비트(이|은|을|과|으로)(?![가-힣])")     # 투비트 ends in a vowel: 가 / 는 / 를 / 와 / 로


# ================================================================ the world
def rule_paper_db(path: str) -> dict:
    """A rule-bot paper file in the store3 schema (paper3.db's shape: no combo_run, no bot name): the account V39_ALL@1h,
    two closed trades, its open position."""
    s = Store3(path)
    eq, out = 1000.0, []
    for sym, side, et, held, reason, e_raw, x_raw in RULE:
        fill, xfill, lev, margin = e_raw * (1 + side * FW.SLIP), x_raw * (1 - side * FW.SLIP), 30, 300.0
        qty = margin * lev / fill
        fees = qty * (fill + xfill) * FW.FEE
        pnl = side * qty * (xfill - fill) - fees
        xt = et + held * H
        d = {"strategy_id": "V39_ALL", "symbol": sym, "timeframe": "1h", "side": side, "entry_time": et, "entry_price": fill,
             "exit_time": xt, "exit_price": xfill, "exit_reason": reason, "qty": qty, "leverage": lev, "margin": margin,
             "fees": fees, "funding": 0.0, "pnl": pnl, "roe": pnl / margin, "context": {}}
        s.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                       "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (TB_ACC, sym, et, xt, reason, lev, pnl, pnl / margin, eq + pnl, json.dumps(d)))
        eq += pnl
        out.append(d)
    sym, side, et, px = RPOS
    stop = round(px * (1 - side * 0.012), 5)
    pos = {"symbol": sym, "side": side, "qty": 300 * 30 / px, "entry_price": px, "entry_time": et, "leverage": 30,
           "tier": "best", "margin": 300.0, "margin_initial": 300.0, "stop_price": stop, "tp_price": None, "liq_price": 0.0,
           "entry_fee": 0.2, "stop_initial": stop, "lock_roe": None,
           "signal": {"ts": et - 1, "symbol": sym, "timeframe": "1h", "strategy_id": "V39_ALL", "side": side,
                      "stop_price": stop, "meta": {}}}
    s.put_state("accounts", NOW - MIN, {"engines": {TB_ACC: {"wallet": eq, "position": pos}}})
    s.put_state("heartbeat", NOW - 2000, {})
    s.close()
    return {"path": path, "trades": out, "position": pos}


def _live(st, pt: dict, fid: int) -> dict:
    """투비트's close of the paper trade ``pt`` (its own key ``V39_ALL@1h|coin|entry``; the fees world's prices and costs)."""
    side, lev, sym = pt["side"], pt["leverage"], pt["symbol"]
    e, x = pt["entry_price"] * (1 + side * 0.0003), pt["exit_price"] * (1 - side * 0.0001)
    qty = 10.0 * lev / e
    key = f"{TB_ACC}|{sym}|{pt['entry_time']}"
    t = {"key": key, "symbol": sym, "side": side, "qty": qty, "leverage": lev, "entry_ts": pt["entry_time"] + 3000, "entry_price": e,
         "stop_initial": e * (1 - side * 0.0125), "stop": e * (1 - side * 0.0125), "mode": "mainnet", "entry_time": pt["entry_time"],
         "paper_entry": pt["entry_price"], "entry_ref": e, "exit_ref": x}
    st.trade_open(t)
    fee_in, fee_out = qty * e * TB_TAKER, qty * x * TB_TAKER
    realized = side * qty * (x - e)
    pnl = realized - fee_in - fee_out
    st.trade_close(key, pt["exit_time"] + 2000, "paper 청산 → 거래소 포지션 닫기", pnl, t, "fills")
    open_side, close_side = ("BUY", "SELL") if side > 0 else ("SELL", "BUY")
    st.fills(key, [{"symbol": sym, "id": fid + 1, "side": open_side, "qty": qty, "price": e, "commission": fee_in, "commissionAsset": "USDT",
                    "time": pt["entry_time"] + 3000, "realizedPnl": 0.0},
                   {"symbol": sym, "id": fid + 2, "side": close_side, "qty": qty, "price": x, "commission": fee_out, "commissionAsset": "USDT",
                    "time": pt["exit_time"] + 2000, "realizedPnl": realized}])
    st.trade_costs(key, {"pnl": pnl, "realized": realized, "commission": fee_in + fee_out, "funding": 0.0, "slippage": 0.0,
                         "real_cost": fee_in + fee_out, "assumed_cost": 2 * qty * e * (FW.FEE + FW.SLIP), "ok": True})
    return {"key": key, "pnl": pnl}


def toobit_db(path: str, cfg_path: str, rp: dict) -> dict:
    """투비트's database (ExecStore) and its config: the owners' template with the account and the paper file filled in."""
    st = ExecStore(path, lock=False)
    st.put_state("meta", V.K(4, 9), {"mode": "mainnet", "account": TB_ACC, "exchange": "toobit"})
    st.event(V.K(4, 9), "INFO", "start", f"시작: paper 계좌 {TB_ACC} 따라 하기 (페이퍼 DB {rp['path']}), mainnet",
             {"paper_db": rp["path"]})
    out = [_live(st, pt, 5000 + 100 * i) for i, pt in enumerate(rp["trades"])]
    p = rp["position"]
    e = p["entry_price"] * (1 + p["side"] * 0.0003)
    trade = {"key": f"{TB_ACC}|{p['symbol']}|{p['entry_time']}", "symbol": p["symbol"], "side": p["side"], "qty": 10.0 * p["leverage"] / e,
             "leverage": p["leverage"], "stop": p["stop_price"], "stop_initial": p["stop_price"], "status": "open",
             "entry_ts": p["entry_time"] + 4_000, "entry_price": e, "entry_time": p["entry_time"], "paper_entry": p["entry_price"],
             "mode": "mainnet", "stop_algo_id": "t1"}
    st.trade_open(trade)
    eq = 50.0 + sum(x["pnl"] for x in out)
    st.equity(V.K(4, 9), 50.0, 50.0, 0.0)
    st.equity(NOW - H, eq, eq, 0.0)
    st.put_state("bot", NOW - 5_000, {"trade": trade, "done": [], "loops": 9000, "mode": "mainnet", "account": TB_ACC,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": eq}})
    st.close()
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.update(account=TB_ACC, paper_db=rp["path"], db=path)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    return {"live": out, "trade": trade, "equity": eq}


@pytest.fixture(scope="module")
def w5(tmp_path_factory):
    """``p5``: the five executors; ``p4``: tests/test_wooxpro2_slot.py's four; ``p40``: the four with the fifth slot's keys
    but neither of its files (a server where it is not installed); ``p2`` / ``p20``: the two executors without and with
    those keys; ``p2t``: the two and 투비트 (no 딥코인: its paper file must not become the page's second paper bot)."""
    folder = str(tmp_path_factory.mktemp("fifth") / "w")
    w = V.build(folder, switch=False)
    p2 = dict(w["p"])
    vt, vwap = w["vt"], p2["paper2"]
    p3 = {**p2, "deepcoin_db": os.path.join(folder, "executor-deepcoin-live.db"),
          "deepcoin_config": os.path.join(folder, "executor-deepcoin.json")}
    V.exec_db(p3["deepcoin_db"], p3["deepcoin_config"], "deepcoin", vwap, [], vwap_closed=[vt["E4"], vt["E5"], vt["E7"]],
              late=[vt["E6"]], open_pos=V.paper_position(vwap), light=(20, 0.75),
              extra={"ladder_from": "own", "risk": {"max_loss_frac": 0.2}})
    fr = W2.friend_db(os.path.join(folder, "friend.db"))
    p4 = {**p3, "wooxpro2_db": os.path.join(folder, "executor-wooxpro2-live.db"),
          "wooxpro2_config": os.path.join(folder, "executor-wooxpro2.json"), "paper3": fr["path"]}
    V.exec_db(p4["wooxpro2_db"], p4["wooxpro2_config"], "wooxpro", fr["path"], fr["trades"][:2], late=[fr["trades"][2]],
              open_pos=fr["position"], light=(0, 0.85),
              extra={"label": "WOO X Pro 2", "ladder_from": "own", "own_keys": True, "equity_floor_frac": 0.7,
                     "double_notice": True, "risk": {"max_loss_frac": 0.35}})
    rp = rule_paper_db(os.path.join(folder, "paper3.db"))
    tb = {"toobit_db": os.path.join(folder, "executor-toobit-live.db"), "toobit_config": os.path.join(folder, "executor-toobit.json")}
    x = toobit_db(tb["toobit_db"], tb["toobit_config"], rp)
    no = os.path.join(folder, "none")
    off = {"toobit_db": no + "-toobit.db", "toobit_config": no + "-toobit.json"}
    p20 = {**p2, **off}
    return {**w, "p5": {**p4, **tb}, "p4": p4, "p40": {**p4, **off}, "p2": p2, "p20": p20, "p2t": {**p2, **tb},
            "rp": rp, "x": x, "folder": folder}


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


@pytest.fixture(scope="module")
def answers(w5):
    more = dict(w5["more"])
    out = {}
    for k in ("p2", "p20", "p4", "p40", "p5"):
        L._cache.clear()
        out[k] = W2._answers(w5[k], more)
    return out


# ================================================================ the live site
def test_not_installed_every_answer_is_as_before(w5, answers):
    """The fifth slot's keys, neither of its files there: the very same answers as without the keys, with two executors
    and with four; nothing of 투비트 anywhere."""
    assert L.installed(w5["p40"]) == L.installed(w5["p4"])
    assert [s[0] for s in L.installed(w5["p40"])] == ["bybit", "mexc", "deepcoin", "wooxpro2"]
    assert L.installed(w5["p20"]) == L.EXECS
    assert W2._flat(answers["p40"]) == W2._flat(answers["p4"]) and W2._flat(answers["p20"]) == W2._flat(answers["p2"])
    for k in ("p40", "p20"):
        words = W2._flat(answers[k])
        assert "toobit" not in words and "투비트" not in words and TB_ACC not in words
    assert sorted(answers["p40"]["build"]["paths"]) == sorted(w5["p4"])        # the answer's paths: as they were


def test_the_slot_shows_once_its_config_or_its_database_is_there(w5):
    p5, folder = w5["p5"], w5["folder"]
    assert [s[0] for s in L.installed(p5)] == ["bybit", "mexc", "deepcoin", "wooxpro2", "toobit"]
    for p, rec, cfg in (({**p5, "toobit_db": os.path.join(folder, "none-t.db")}, "missing", "ok"),
                        ({**p5, "toobit_config": os.path.join(folder, "none-t.json")}, "ok", "missing")):
        assert [s[0] for s in L.installed(p)][-1] == "toobit"
        _c, _f, _paper, execs = L.sources(p, NOW)
        x = execs[-1]
        assert (x["id"], x["name_ko"], x["record"]["state"], x["config"]["state"]) == ("toobit", "투비트", rec, cfg)
    d = L.paths({})
    assert (d["toobit_db"], d["toobit_config"]) == ("/var/lib/paperbot/exec/executor-toobit-live.db",
                                                    "/etc/paperbot/executor-toobit.json")
    assert (L.ENV["toobit_db"][0], L.ENV["toobit_config"][0]) == ("PAPERBOT_LIVE_TOOBIT_DB", "PAPERBOT_LIVE_TOOBIT_CONFIG")
    assert L.paths({"PAPERBOT_LIVE_TOOBIT_CONFIG": p5["toobit_config"]})["toobit_db"] == p5["toobit_db"]
    assert L.shown_paths(w5["p40"]) == w5["p4"] and L.shown_paths(p5) == p5
    env = (ROOT / "deploy" / "dash.env.example").read_text(encoding="utf-8")
    for line in ("#PAPERBOT_LIVE_TOOBIT_DB=/var/lib/paperbot/exec/executor-toobit-live.db",
                 "#PAPERBOT_LIVE_TOOBIT_CONFIG=/etc/paperbot/executor-toobit.json"):
        assert line in env
    # the server's own paths are the unit's and the template's (deploy/paperbot-executor-toobit.service)
    unit = (ROOT / "deploy" / "paperbot-executor-toobit.service").read_text(encoding="utf-8")
    assert f"--config {L.ENV['toobit_config'][1]}" in unit
    assert json.loads(TEMPLATE.read_text(encoding="utf-8"))["db"] == L.ENV["toobit_db"][1]


def test_its_name_is_its_exchanges():
    ok = lambda ex, **k: {"state": "ok", "exchange": ex, **k}                       # noqa: E731
    got = L.slots({"bybit": ok("bybit"), "mexc": ok("wooxpro"), "deepcoin": ok("deepcoin"),
                   "wooxpro2": ok("wooxpro", label="WOO X Pro 2"), "toobit": ok("toobit")})
    assert [ko for _x, ko, _d, _c in got] == ["바이비트", "WOO X Pro", "딥코인", "WOO X Pro 2", "투비트"]
    assert L.slots({"toobit": {"state": "missing"}})[-1][:2] == ("toobit", "투비트")        # unread: the slot's own name
    assert L.EX_NAME["toobit"] == LC.EX_KO["toobit"] == LPOS.EX_KO["toobit"] == "투비트"
    c = L.read_config(str(TEMPLATE))                                     # the owners' template as it is
    assert c["state"] == "ok" and c["exchange"] == "toobit" and "label" not in c
    assert LT.SHORT["toobit"] == "T" and len(set(LT.SHORT.values())) == len(LT.SHORT)


def test_the_site_with_five_executors(w5, answers):
    a = answers["p5"]
    b = a["build"]
    assert [(x["id"], x["name_ko"], x.get("follows_ko")) for x in b["execs"]] == [
        ("bybit", "바이비트", "추세판단 봇"), ("mexc", "WOO X Pro", "추세판단 봇"), ("deepcoin", "딥코인", "VWAP 개선판"),
        ("wooxpro2", "WOO X Pro 2", "친구 매매법"), ("toobit", "투비트", f"페이퍼 {TB_ACC}")]
    tb = next(x for x in b["accts"] if x["id"] == "toobit")
    assert tb["state"] == "ok" and tb["kind"] == "live" and tb["name_ko"] == "투비트"
    assert tb["position"]["symbol"] == "DOGEUSDT" and tb["follows_ko"] == f"페이퍼 {TB_ACC}"
    # the page's paper bots are the two as before: its paper file is never an account of the page nor the second bot
    assert [x["id"] for x in b["papers"]] == ["paper", "paper2"] and b["papers"][1]["name"] == "VWAP 개선판"
    assert not [x for x in b["accts"] if x["id"] not in ("paper", "paper2", "bybit", "mexc", "deepcoin", "wooxpro2", "toobit", "flip")]
    assert sorted(b["paths"]) == sorted(w5["p5"])
    # 거래: its own table, each trade paired with the rule-bot trade it followed (its account in its own file)
    rows = a["trades"]["accts"]["toobit"]["rows"]
    assert sorted(r["key"] for r in rows) == sorted(x["key"] for x in w5["x"]["live"])
    assert {r["paper"]["exit_reason"] for r in rows} == {"LOCK", "SL"} and all(r["paper"]["strategy_id"] == "V39_ALL" for r in rows)
    cells = [r["live"]["toobit"] for r in a["trades"]["accts"]["paper"]["rows"]]     # the main bot's trades: never its own
    assert {c["state"] for c in cells} == {"other", "before"}
    assert {c["why_ko"] for c in cells if c["state"] == "other"} == {"이때 투비트는 다른 페이퍼를 따라갔어요"}
    # 포지션 · 비용 · 안전 · 설정 · 봇 상태 · 위험 · 성적
    assert [x["id"] for x in a["pos"]["cards"]] == ["paper", "paper2", "bybit", "mexc", "deepcoin", "wooxpro2", "toobit", "flip"]
    card = next(x for x in a["pos"]["cards"] if x["id"] == "toobit")
    assert card["position"] and card["position"]["symbol"] == "DOGEUSDT" and card["follows_ko"] == f"페이퍼 {TB_ACC}"
    c = a["costs"]
    assert c["execs"][-1] == {"id": "toobit", "name_ko": "투비트"} and c["accts"]["toobit"]["n"] == 2
    fee = next(x for x in c["fees"]["execs"] if x["id"] == "toobit")
    assert fee["exchange"] == "toobit" and fee["rates"]["taker"] == 0.0006 and fee["rates"]["maker"] is None
    assert [x["id"] for x in a["safety"]["execs"]] == ["bybit", "mexc", "deepcoin", "wooxpro2", "toobit"]
    assert [(x["id"], x.get("follows_ko")) for x in a["settings"]["execs"]][-1] == ("toobit", f"페이퍼 {TB_ACC}")
    assert [(i["who"], i["ko"]) for i in a["health"]["items"] if i.get("id") == "exec"][-1] == ("toobit", "투비트 실행기")
    assert a["risk"]["kill"]["what_ko"].startswith("다섯 실행기가 모두 멈춰요")
    assert answers["p4"]["risk"]["kill"]["what_ko"].startswith("네 실행기가 모두 멈춰요")
    assert "toobit" in a["perf"]["accts"] and "toobit" in a["groups"]["accts"]
    assert [x["id"] for x in a["vwap"]["followers"]] == ["deepcoin"]                # the VWAP bot's page: its own executor only
    words = W2._flat(a)
    assert "투비트" in words and not WRONG_JOSA.search(words), WRONG_JOSA.search(words)


def test_its_paper_never_takes_the_second_paper_bots_place(w5):
    """Without 딥코인 (the executor that makes the VWAP bot the second paper bot) the VWAP bot is still the second, from its
    file; 투비트's rule-bot file stays its own."""
    L._cache.clear()
    b = L.build(w5["p2t"], NOW)
    assert [(x["id"], x["path"]) for x in b["papers"]] == [("paper", w5["p2"]["paper"]), ("paper2", w5["p2"]["paper2"])]
    assert [(x["id"], x.get("follows_ko")) for x in b["execs"]][-1] == ("toobit", f"페이퍼 {TB_ACC}")
    assert L.SIDE_PAPER_EXECS == ("toobit",)


def test_the_cost_tab_says_toobits_documented_rates():
    r = F.RATES["toobit"]
    assert (r["taker"], r["maker"], r["src"]) == (0.0006, None, "docs/toobit-ko.md")     # a maker rate nobody wrote: 모름
    doc = FW._read(ROOT, r["src"])
    assert "0.06%" in doc and not re.search(r"메이커\s*\d", doc)
    assert F.rates_of("toobit")["taker_disc"] is None


SCREENS_JS = """
const view = async (sum, tr, sf, co) => {
  K.setPapers(sum.papers); K.setExecs(sum.execs);
  const band = P.bandLine(mkCtx(null)); band.set(sum, "ok");
  const hub = {get: () => sum, state: () => "ok", at: () => sum.now_ms, retry: () => {}};
  const hq = await run(HQ.hqView, (p) => (p.endsWith('/now') ? D_now : {}), hub);
  hq.set(sum, "ok");
  const hqw = D.walk(hq.el);
  const t = await run(TR.tradesView, tr), s = await run(SF.safetyView, sf), c = await run(CO.costView, co);
  return {real: texts(ui.note(K.realLine(sum))), band: texts(band.el), hq: hqw.text.replace(/\\s+/g, ' '),
    reactors: hqw.classes.filter((x) => x.split(' ').includes('lbh-reactor')).length, deck: hqw.classes.find((x) => x.startsWith('lbh-deck')),
    trades: texts(t.el), safety: texts(s.el), cost: texts(c.el), costCards: D.walk(c.el).classes.filter((x) => /lbk-a-toobit/.test(x)).length,
    tbReactor: hqw.classes.filter((x) => x.split(' ').includes('lbh-x-toobit') && x.split(' ').includes('lbh-reactor')).length};
};
const four = await view(D_s4, D_t4, D_f4, D_c4);
const five = await view(D_s5, D_t5, D_f5, D_c5);
const ids5 = [K.execsNow(), K.execIds(D_s5), K.execIds(D_t5), K.execIds(D_c5), PE.idsOf(D_p5), MA.idsOf({accounts: {toobit: {}}}),
  K.execsKo(), K.acctsKo(7), K.countKo(5), K.countKo(4), K.countKo(3), K.countKo(2)];
console.log(JSON.stringify({four, five, ids5}));
"""


def test_the_screens_in_node(w5, answers, tmp_path):
    a4, a5 = answers["p40"], answers["p5"]
    out = W2._node(tmp_path, SCREENS_JS, s4=a4["build"], t4=a4["trades"], f4=a4["safety"], c4=a4["costs"],
                   s5=a5["build"], t5=a5["trades"], f5=a5["safety"], c5=a5["costs"], p5=a5["perf"], now=a5["now"])
    four, five = out["four"], out["five"]
    for k, t in four.items():                              # not installed: nothing of it anywhere
        assert "투비트" not in str(t), k
    assert four["reactors"] == 5 and four["tbReactor"] == 0 and "six" not in four["deck"].split()
    ids = out["ids5"]
    assert ids[:4] == [["bybit", "mexc", "deepcoin", "wooxpro2", "toobit"]] * 4
    assert ids[4] == ["paper", "paper2", "bybit", "mexc", "deepcoin", "wooxpro2", "toobit"] and ids[5][-1] == "toobit"
    assert ids[6] == "바이비트 · WOO X Pro · 딥코인 · WOO X Pro 2 · 투비트" and ids[7] == "일곱 계좌"
    assert ids[8:] == ["다섯", "네", "세", "두"]
    # 한눈에: its own reactor next to the five cards, two rows of three on a wide screen
    assert five["reactors"] == 6 and five["tbReactor"] == 1 and {"five", "six"} <= set(five["deck"].split())
    assert "투비트 진짜 돈" in five["hq"] and f"따라감 · 페이퍼 {TB_ACC}" in five["hq"]
    assert "투비트 $" in five["real"] and "투비트 $" in five["band"]
    assert "투비트" in five["trades"]                                     # its table is a choice
    assert "실행기 다섯 개" in five["safety"] and five["costCards"] >= 1 and "투비트 실거래 · 진짜 돈" in five["cost"]
    for k, t in five.items():
        assert not BAD.search(str(t)), (k, BAD.search(str(t)))
        assert not WRONG_JOSA.search(str(t)), (k, WRONG_JOSA.search(str(t)))


def test_the_house_rules_of_the_fifth_slot():
    kit = FW._read(SCREENS, "livebots-kit.js")
    assert 'export const EXEC_SLOTS = ["bybit", "mexc", "deepcoin", "wooxpro2", "toobit"];' in kit
    assert 'toobit: {ko: "투비트", s: "T"' in kit
    shorts = re.findall(r'^  \w+: \{ko: "[^"]+", s: "(\w+)"', kit, re.M)
    assert "T" in shorts and len(shorts) == len(set(shorts)), shorts
    # the server's slot list and the screens' are one list, in one order
    assert [s[0] for s in L.ALL_EXECS] == json.loads(re.search(r"export const EXEC_SLOTS = (\[.*?\]);", kit).group(1))
    css = FW._read(os.path.dirname(SCREENS), "tokens.css")
    assert "--series-tb: hsl(95 var(--av-s) var(--av-ring-l));" in css
    for f, cls in (("livebots.css", ".lb-a-toobit .lb-sw"), ("livebots-hq.css", ".lbh-x-toobit"), ("livebots-cost.css", ".lbk-a-toobit"),
                   ("livebots-map.css", ".lbm-a-toobit"), ("livebots-map.css", ".lbm-l-toobit"), ("livebots-risk.css", ".lbv-a-toobit"),
                   ("livebots-goal.css", ".lbg-a-toobit"), ("livebots-expect.css", ".lex-a-toobit"),
                   ("livebots-expect.css", ".lex-l-toobit")):
        assert cls in FW._read(SCREENS, f), (f, cls)
    hq = FW._read(SCREENS, "livebots-hq.css")
    assert ".lbh-deck > .lbh-x-toobit { order: 6; }" in hq and ".lbh-deck.six { grid-template-columns: repeat(3, minmax(0, 1fr)); }" in hq
    for f, word in (("livebots-pos.js", 'toobit: "투비트"'), ("livebots-map.js", 'toobit: "투비트"'),
                    ("livebots-replay.js", 'toobit: read("--series-tb")')):
        assert word in FW._read(SCREENS, f), (f, word)


# ================================================================ the live checks and the Telegram messages
def _specs(tmp_path):
    cfg, db = tmp_path / "executor-toobit.json", tmp_path / "executor-toobit-live.db"
    spec = (("toobit", str(cfg), "paperbot-executor-toobit", str(db), 0, 0.85),)
    base = tuple((n, str(tmp_path / f"{n}.json"), u, str(tmp_path / f"{n}.db"), k, s) for n, _p, u, _d, k, s in LC.EXECUTORS)
    return cfg, db, spec, base


def test_livecheck_reads_it_only_once_installed(tmp_path, monkeypatch):
    cfg, db, spec, base = _specs(tmp_path)
    monkeypatch.setattr(LC, "OPTIONAL_EXECUTORS", spec)
    assert LC.installed_specs(base, spec) == base                          # neither file: the executors as before
    assert [e.name for e in LC.load_executors(LC.installed_specs(base, spec))] == ["bybit", "mexc"]
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))                 # the owners' template as it is
    raw.update(db=str(db))
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    infos = LC.load_executors(LC.installed_specs(base, spec))
    assert [e.name for e in infos] == ["bybit", "mexc", "toobit"]
    f = infos[-1]
    assert (f.label, f.unit, f.db, f.light_n, f.budget, f.margin_frac, f.max_loss, f.exchange, f.problem) == (
        "투비트", "paperbot-executor-toobit", str(db), 0, 50.0, 0.4, None, "toobit", "")
    assert f.fee == LC.ASSUMED_FEE["toobit"] == 0.0006 and LC.pad_of("toobit", f.label) == "투비트   "
    assert len(LC.PAD["toobit"].encode("euc-kr")) == len(LC.PAD["bybit"].encode("euc-kr")) == 9    # the same width
    cfg.unlink()
    db.write_bytes(b"")                                  # the database alone: installed too (the site's rule)
    assert [x[0] for x in LC.installed_specs(base, spec)] == ["bybit", "mexc", "toobit"]
    monkeypatch.undo()
    # this server's own: the unit's and the template's paths, after the four before it
    assert [x[0] for x in LC.OPTIONAL_EXECUTORS] == ["deepcoin", "wooxpro2", "toobit"]
    assert LC.OPTIONAL_EXECUTORS[-1] == ("toobit", "/etc/paperbot/executor-toobit.json", "paperbot-executor-toobit",
                                         "/var/lib/paperbot/exec/executor-toobit-live.db", 0, 0.85)
    assert LC.OPTIONAL_EXECUTORS[-1][1] == L.ENV["toobit_config"][1] and LC.OPTIONAL_EXECUTORS[-1][3] == L.ENV["toobit_db"][1]


def test_its_fee_is_the_same_everywhere():
    """0.06 % a side: the executor's net costs, the template, the checks' assumption, the cost tab's taker rate."""
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert E.NET_COSTS["toobit"]["taker_fee"] == raw["net_costs"]["toobit"]["taker_fee"] == LC.ASSUMED_FEE["toobit"] \
        == F.RATES["toobit"]["taker"] == 0.0006
    assert LC.ExecInfo("toobit", "", "", "", 0, 0.85, exchange="toobit").fee == 0.0006


def test_the_stop_file_words_count_five_and_low_memory_never_suggests_it():
    assert LC.every_ko(4) == "네 실행기 모두" and LC.every_ko(5) == "다섯 실행기 모두" and LC.every_ko(2) == "두 실행기 모두"
    five = [LC.ExecInfo(n, "", "", "", 0, 0.85, kill_file="/var/lib/paperbot/STOP")
            for n in ("bybit", "mexc", "deepcoin", "wooxpro2", "toobit")]
    assert "(다섯 실행기 모두 바로 닫고 멈추려면 sudo touch /var/lib/paperbot/STOP)" in LC.streak_todo(five)
    tb = LC.ExecInfo("toobit", "", "paperbot-executor-toobit", "", 0, 0.85, exchange="toobit")
    assert "다섯 실행기 모두 바로 닫고 멈추려면" in LC.dd_halt_words(tb, 5)
    assert "paperbot-executor-toobit.service" in LC.PROTECTED_UNITS and not LC.experiment("paperbot-executor-toobit.service")
    lines = LC.memory_lines([("paperbot-agents.service", 900 * 1024 ** 2)], ("paperbot-executor-toobit",))
    assert lines[1].endswith("paperbot-combo-mexc, paperbot-executor-toobit")


def test_low_memory_keeps_it_once_installed(tmp_path):
    ex = LC.ExecInfo("toobit", "", "paperbot-executor-toobit", "", 0, 0.85, exchange="toobit")
    src = LC.Sources(db=str(tmp_path / "lc.db"), executors=[ex], paper2_db=str(tmp_path / "none-vwap.db"))
    host = LC.Host(disk_free=lambda p: 40 * 1024 ** 3, mem_available=lambda: 100 * 1024 ** 2,
                   unit_memory=lambda: [("paperbot-agents.service", 900 * 1024 ** 2)], paths=(str(tmp_path),))
    conds, _judged = LC.health_conditions(host, src)
    mem = next(c for c in conds if c.key == "memory")
    assert "paperbot-combo-mexc, paperbot-executor-toobit" in mem.text


def _toobit(tmp_path, trades=(), fee=TB_TAKER, equity=((TL.W0 - DAY, 50.0),)):
    db = TL.exec_db(tmp_path / "toobit.db", trades=list(trades), equity=list(equity))
    return LC.ExecInfo(name="toobit", config="-", unit="paperbot-executor-toobit", db=str(db), light_n=0, light_min=0.85,
                       exchange="toobit", budget=50.0, kill_file="/nonexistent/STOP")


def test_the_morning_check_scores_it_by_name_with_its_fee(tmp_path):
    for fee, flag in ((TB_TAKER, False), (0.0007, True)):
        d = tmp_path / f"f{fee}"
        d.mkdir()
        src, rep = TL._setup(d)
        xt = [TL.xtrade(TL.W0 + 10 * H, entry_price=100.02, exit_price=100.97, pnl=-0.3, fee=fee)]
        src.executors.append(_toobit(d, xt, fee, equity=[(TL.W0 - DAY, 50.0), (TL.NOW - MIN, 49.7)]))
        n = ListNotifier()
        out = LC.run_check(src, day="2026-10-20", now_ms=TL.NOW, replay=lambda *a: rep, notifier=n)
        text = n.messages[0][1]
        assert re.search(r"^- 투비트 1번 [-+]\$0\.\d\d: 진입 [-+]\d", text, re.M), text
        assert f"수수료 {fee:.3%}(가정 0.060%)" in text
        assert "- 투비트: 거래 1번 · 0승(0%) · 실현 -$0.30 · 잔고 $49.70" in text
        assert [r["label"] for r in out["report"]["executors"]] == ["바이비트", "MEXC", "투비트"]
        assert ("- 투비트 수수료가 0.070%로 가정 0.060%보다 높습니다" in text) is flag
        assert not WRONG_JOSA.search(text)


def test_the_watcher_tells_its_start_and_its_stop_by_name(tmp_path):
    src = TL.watch_setup(tmp_path, entry=None)
    tb = _toobit(tmp_path)
    src.executors.append(tb)
    n = ListNotifier()
    TL.run(src, TL.T, n)                                              # first look: recorded, nothing sent
    assert not TL.msgs(n, "▶️")
    st = ExecStore(tb.db, lock=False)
    st.event(TL.T + MIN, "INFO", "start", "시작")
    st.commit()
    st.close()
    TL._set_bot(tb.db, last_equity=50.0)
    TL.run(src, TL.T + 2 * MIN, n)
    (lv, text), = TL.msgs(n, "▶️")
    assert lv == INFO and text == "▶️ 투비트 실행기 켜짐 · 잔고 $50.00"
    st = ExecStore(tb.db, lock=False)
    st.event(TL.T + 3 * MIN, "INFO", "sigterm", "끄라는 신호(SIGTERM)")
    st.commit()
    st.close()
    TL.run(src, TL.T + 4 * MIN, n)
    (lv, text), = TL.msgs(n, "⏹")
    assert lv == INFO and text.startswith("⏹ 투비트 실행기 꺼짐 (끄라는 신호를 받음: 사람이 끔이나 서버 재시작)")
    assert text.endswith("다시 켜기: sudo systemctl start paperbot-executor-toobit")


def test_the_team_reads_it_once_installed(w5, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none-combo.json"))
    infos = T.bot_world(w5["p5"])["infos"]
    assert [e.name for e in infos] == ["bybit", "mexc", "deepcoin", "wooxpro2", "toobit"]
    assert (infos[-1].label, infos[-1].account, infos[-1].fee) == ("투비트", TB_ACC, 0.0006)
    assert [e.name for e in T.bot_world(w5["p40"])["infos"]] == ["bybit", "mexc", "deepcoin", "wooxpro2"]


def test_the_guides_say_where_it_shows():
    doc = (ROOT / "docs" / "livedash-ko.md").read_text(encoding="utf-8")
    assert "### 다섯 번째 실행기 (투비트, 10/25)" in doc and "`PAPERBOT_LIVE_TOOBIT_DB`" in doc
    assert "tests/test_toobit_slot.py" in FW._read(os.path.dirname(SCREENS), "INVENTORY.md")


def test_no_toobit_file_is_opened_by_the_checks_on_a_server_without_it(tmp_path, monkeypatch):
    """The default specs on a server without the slot (neither path there): load_executors never lists it."""
    _cfg, _db, spec, base = _specs(tmp_path)
    monkeypatch.setattr(LC, "OPTIONAL_EXECUTORS", spec)
    monkeypatch.setattr(LC, "EXECUTORS", base)
    assert [e.name for e in LC.load_executors()] == ["bybit", "mexc"]
