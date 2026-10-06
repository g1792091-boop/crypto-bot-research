"""add-accounts (owners 10/06 "전부 지금"): the review items on 계좌, 결재함 and the meeting links.

- 흐름 레이스: outside events nearer than 40 px share one mark, names stacked (FOMC over PCE, never "FOMCE");
- 회의 '근거': packet paths in plain Korean (loss_cards[0].tags -> 손실 카드 1번 › 태그), JSON never shown raw;
- 한눈 지도: the default colour is the account's own return (a big loss is never gold), 동전 봇 대비 second;
- 계좌 '왜 이 수익률인가' card: fees / funding waterfall, exit reasons, win rate vs the break-even rate, the biggest
  losses with their replays; DeepSeek: exit-reason counts only (no money, owners' D10 / D11);
- 승인한 복제 계좌: 원본 vs 복제 over the same period (/api/v4/copycmp/<id>);
- 손실 거래 <-> 회의 (/api/v4/losslinks): trade ids the loss meetings stored, checked against the trades' exit times;
- 결재함 (/api/v4/approvals + #/inbox): the 5-year table, for / against lines, what approving does; approving goes
  through the existing POST /api/proposals/<id>/decide only.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")


def _read(name, folder=SCREENS):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return f.read()


def _node(imports: str, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + SCREENS
    script = imports.replace("{base}", base) + "\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- 흐름: event labels
def test_close_events_share_one_mark():
    out = _node("const K = await import('{base}/flow-kit.js');", """
      const ev = (x, kind) => ({x, ev: {kind}});
      const c = K.clusterEvents([ev(300, "PCE"), ev(280, "FOMC"), ev(100, "CPI"), ev(500, "NFP"), ev(530, "CPI")]);
      console.log(JSON.stringify({n: c.length, groups: c.map((g) => g.items.map((e) => e.ev.kind)), xs: c.map((g) => g.x),
        gap: K.EV_GAP, none: K.clusterEvents([]).length, bad: K.clusterEvents([{x: NaN, ev: {}}]).length}));""")
    assert out["gap"] == 40
    assert out["groups"] == [["CPI"], ["FOMC", "PCE"], ["NFP", "CPI"]]   # 20 px apart: one mark, both names
    assert out["xs"] == [100, 290, 515]                                    # the mark sits between them
    assert out["none"] == 0 and out["bad"] == 0
    src = _read("flow-kit.js")
    assert "clusterEvents(evs)" in src and "names.map((n, i) => s(\"text\"" in src


# ---------------------------------------------------------------- 회의 '근거' in plain words
def test_evidence_paths_read_in_korean_and_never_as_json():
    out = _node("const E = await import('{base}/rooms-evidence.js');", """
      const p = (x) => E.pathKo(x);
      const g = E.evidenceGroups({evidence: ["board.today.trades", {path: "losses.tag_stats.0.losses", value: 3}, {a: {b: 1}}]}, {});
      const gc = E.evidenceGroups({evidence: ["x"]}, {findings: [{claim: "손절 2건이 추세 반대", evidence: ["loss_cards[0].tags"]}],
        objections: [{claim: "표본 적음", evidence: ["code_result.result.periods.2.diff"]}]});
      console.log(JSON.stringify({a: p("loss_cards[0].tags"), b: p("losses.tag_stats.0.losses"), c: p("board.today.trades"),
        d: p("specialist.by_strategy.15m.mean_roe"), e: p("meta.weird_new_key_xyz"), f: p("by_coin.BTCUSDT.pnl"), g: p(""),
        flat: g, claims: gc, n: E.evidenceCount(gc), v: [E.valueKo(0.123456), E.valueKo(1234.5), E.valueKo({x: 1}), E.valueKo(["a", "b"])]}));""")
    assert out["a"] == "손실 카드 1번 › 태그"
    assert out["b"] == "손실 › 태그 통계 1번 › 손실"
    assert out["c"] == "순위 자료 › 오늘 › 거래 수"
    assert out["d"] == "전담 자료 › 봉별 › 15분봉 › 거래당 평균 ROE"
    assert out["e"] == "기본 정보 › 세부 항목"                          # an unknown key: never the raw English
    assert out["f"] == "코인별 › BTC › 손익" and out["g"] == "세부 항목"
    flat = out["flat"][0]
    assert flat["claim"] is None and [i["name"] for i in flat["items"]] == ["순위 자료 › 오늘 › 거래 수", "손실 › 태그 통계 1번 › 손실",
                                                                         "세부 자료"]
    assert flat["items"][1]["value"] == "3"
    assert not any("{" in i["name"] for i in flat["items"])              # an object is never printed as JSON
    assert [c["claim"] for c in out["claims"]] == ["손절 2건이 추세 반대", "표본 적음"] and out["n"] == 2
    assert out["claims"][1]["items"][0]["name"] == "코드 계산 결과 › 결과 › 2기간 › 차이"     # a period id, not a list index
    assert out["v"][0] == "0.1235" and out["v"][1] == "1,235" and out["v"][2] is None and out["v"][3] == "a, b"
    src = _read("rooms-chat.js")
    assert "JSON.stringify(x)" not in src and "evidenceList(evg)" in src


# ---------------------------------------------------------------- 한눈 지도: own return first
def test_grid_default_colour_is_the_accounts_own_return():
    g, kit, css = _read("grid.js"), _read("grid-kit.js"), _read("grid-kit.css")
    colors = re.search(r"const COLORS = \[([^\]]*)\]", g).group(1)
    assert re.findall(r'id: "(\w+)"', colors)[:2] == ["own", "vs"]           # 자기 수익률 first, 동전 봇 대비 second
    assert 'local.get("grid-color", "own")' in g and 'st.color = "own"' in g
    assert 'vsMark: mode === "own" && group !== "ds200"' in g                 # DeepSeek never gets the coin-flip mark
    assert "o.vsMark && !grey && !c.bust" in kit and '"▲" : "▼"' in kit
    # the mark is neutral (never the up / down colours) and the 5분봉 strip is coloured by its own return too
    mark = re.search(r"\.gk-vsm \{([^}]*)\}", css).group(1)
    assert "--up" not in mark and "--down" not in mark and "--t-2xs" in mark
    assert 'heatCell(reel, {mode: "own", vsMark: true' in g


# ---------------------------------------------------------------- 계좌: 왜 이 수익률인가
def test_why_card_numbers_from_the_trades():
    out = _node("const W = await import('{base}/account-why.js');", """
      const t = (id, pnl, fees, funding, r, sym) => ({id, pnl, fees, funding, exit_reason: r, symbol: sym || "BTCUSDT", exit_time: id});
      const rows = [t(1, -200, 20, 5, "SL"), t(2, 60, 18, 1, "LOCK"), t(3, -400, 25, -2, "LIQ"), t(4, 62, 18, 0, "LOCK"),
                    t(5, -100, 15, 3, "SL"), t(6, 58, 17, 1, "LOCK")];
      const s = W.whyStats(rows, {initial: 5000, wallet: 4480, flipMed: 4700, total: 9});
      const f = W.waterfall(s);
      const none = W.whyStats([], {initial: 5000, wallet: 5000});
      console.log(JSON.stringify({s, f, none}));""")
    s, f = out["s"], out["f"]
    assert s["n"] == 6 and s["total"] == 9 and s["capped"] is True          # the server's latest rows only: said so
    assert abs(s["net"] - (-520)) < 1e-9 and abs(s["fees"] - 113) < 1e-9 and abs(s["funding"] - 8) < 1e-9
    assert abs(s["gross"] - (-520 + 113 + 8)) < 1e-9                          # pnl = before − fees − funding (engine)
    assert [r["reason"] for r in s["byReason"]] == ["SL", "LOCK", "LIQ"]
    assert [r["n"] for r in s["byReason"]] == [2, 3, 1] and s["byReason"][2]["pnl"] == -400
    assert abs(s["winRate"] - 0.5) < 1e-9 and abs(s["avgWin"] - 60) < 1e-9 and abs(s["avgLoss"] - 700 / 3) < 1e-9
    assert abs(s["breakeven"] - (700 / 3) / (60 + 700 / 3)) < 1e-9            # avg loss / (avg win + avg loss)
    assert [x["id"] for x in s["big"]] == [3, 1, 5] and abs(s["bigShare"] - 1) < 1e-9
    assert abs(s["ret"] - (-0.104)) < 1e-9 and abs(s["flipRet"] - (-0.06)) < 1e-9 and abs(s["rest"] - (-0.044)) < 1e-9
    assert [x["key"] for x in f] == ["gross", "fees", "funding", "net"]
    assert f[1]["from"] == f[0]["to"] and abs(f[2]["to"] - s["net"]) < 1e-9 and f[3]["from"] == 0
    assert out["none"]["n"] == 0 and out["none"]["winRate"] is None and out["none"]["breakeven"] is None


def test_why_card_wiring_and_deepseek_counts_only():
    acc, why, css = _read("account.js"), _read("account-why.js"), _read("account.css")
    assert 'whyCard(a, d, {initial: init' in acc and 'countOnly: a.kind === "ds200"' in acc
    assert ".filter(Boolean));" in acc                                       # no "null" text between the cards
    # DeepSeek: exit-reason counts only, no money anywhere in that branch
    branch = why[why.index("if (o.countOnly) {"):why.index("const kids = [], secs = [];")]
    assert "fmt.money" not in branch and "signed(" not in branch and "pnl" not in branch.replace("no money", "")
    assert 'ui.assume("closed"' in why and "ui.smallSample(s.n)" in why
    assert 'fmt.groupOf(a) !== "extra"' in why and 'a.kind !== "random"' in why   # no coin-flip line for extras / flips
    assert re.search(r"\.acw-fbar\.cost \{ background: var\(--warn\); \}", css)


# ---------------------------------------------------------------- a small paper3.db for the server routes
H = 3_600_000
T0 = 1_790_000_000_000          # the copy's start


def _trade(st, aid, entry, exit_t, pnl, roe, reason="SL", fees=2.0, funding=0.5, sym="BTCUSDT", after=0.0):
    from paperbot.models import TradeRecord
    strat, tf = aid.split("~")[0].split("@")
    st.trade(aid, TradeRecord(strategy_id=strat, symbol=sym, timeframe=tf, side=1, signal_ts=entry - 1, entry_time=entry,
                              entry_price=100.0, exit_time=exit_t, exit_price=99.0, exit_reason=reason, qty=1.0, leverage=30,
                              tier="normal", margin=100.0, stop_price=99.0, tp_price=float("nan"), liq_price=97.0, fees=fees,
                              funding=funding, pnl=pnl, roe=roe, price_move=-0.01, mae_price=99.0, mfe_price=100.0,
                              equity_after=after, score=0.0, context={}))


def _paper(path):
    from paperbot.store3 import Store3
    st = Store3(path)
    st.add_account("S@15m", "S", "15m", "strategy", T0 - 100 * H, "v4")
    st.add_account("S@15m~c1", "S", "15m", "copy", T0, "v4", "S@15m", {"v": 1, "rule": {"template": "stop_atr", "k": 2.5},
                                                                       "label_ko": "S 15분 복제 c1"})
    st.add_account("D@15m", "D", "15m", "ds200", T0 - 100 * H, "v4", None, {"group": "x"})
    for k in (1, 2, 3):
        st.add_account(f"RANDOM_{k}@15m", f"RANDOM_{k}", "15m", "random", T0 - 100 * H, "v4")
    # equity rows are marked to market (an open position's unrealised P&L in them): never the comparison's base
    st.equity("S@15m", T0 - 100 * H, 5000.0, 0.0)
    st.equity("S@15m", T0 - H, 2600.0, 0.0)
    st.equity("S@15m~c1", T0 + 5 * H, 4100.0, 0.0)
    for k, (a, b) in enumerate(((4000.0, 4400.0), (5000.0, 4500.0), (3000.0, 3300.0)), 1):
        _trade(st, f"RANDOM_{k}@15m", T0 - 5 * H, T0 - 2 * H, a - 5000.0, -0.1, after=a)  # balance at the copy's start
    _trade(st, "S@15m", T0 - 3 * H, T0 - 2 * H, -3000.0, -0.3, after=2000.0)            # ended before the copy: out
    # open when the copy started, ended after it: in the period's return, so in its trade rows too
    _trade(st, "S@15m", T0 - H // 2, T0 + H // 2, 50.0, 0.05, "LOCK", fees=6.0, funding=1.0, after=2050.0)
    _trade(st, "S@15m", T0 + H, T0 + 2 * H, 150.0, 0.15, "LOCK", fees=4.0, funding=1.0, after=2200.0)
    _trade(st, "S@15m~c1", T0 + H, T0 + 2 * H, -400.0, -0.08, "SL", fees=10.0, funding=2.0, after=4600.0)
    _trade(st, "S@15m~c1", T0 + 3 * H, T0 + 4 * H, -100.0, -0.02, "LIQ", fees=10.0, funding=3.0, after=4500.0)
    _trade(st, "D@15m", T0 + H, T0 + 2 * H, -10.0, -0.1)
    st.put_state("accounts", T0 + 5 * H, {"engines": {"S@15m": {"wallet": 2200.0}, "S@15m~c1": {"wallet": 4500.0},
                                                      "RANDOM_1@15m": {"wallet": 4400.0}, "RANDOM_2@15m": {"wallet": 4500.0},
                                                      "RANDOM_3@15m": {"wallet": 3300.0}}})
    st.commit()
    st.conn.close()
    return path


def test_copy_vs_parent_over_the_same_period(tmp_path):
    from fastapi import HTTPException
    from paperbot.dash.more import copycmp as CC
    db = _paper(str(tmp_path / "paper3.db"))
    before = open(db, "rb").read()
    d = CC.compare(db, "S@15m~c1", now_ms=T0 + 6 * H)
    assert d["parent_id"] == "S@15m" and d["rule_ko"] == "손절 2.5 ATR" and d["since"] == T0 and not d["count_only"]
    p, c = d["parent"], d["copy"]
    assert p["trades"] == 2 and p["wins"] == 2                       # the trades that ended in the period
    assert abs(p["ret"] - (2200 / 2000 - 1)) < 1e-9                  # from ITS closed balance at the copy's start
    assert p["start_balance"] == 2000 and c["start_balance"] == 5000   # not 5,000; not the marked-to-market 2,600
    assert abs(c["ret"] - (4500 / 5000 - 1)) < 1e-9 and c["liquidations"] == 1
    assert abs(p["fees_share"] - 10 / 2000) < 1e-9 and abs(c["fees_share"] - 20 / 5000) < 1e-9
    assert abs(p["mean_roe"] - 0.1) < 1e-9 and c["small"] is True
    assert abs(d["diff"] - (c["ret"] - p["ret"])) < 1e-9
    assert d["flips"]["n"] == 3 and abs(d["flips"]["median_ret"] - 0.1) < 1e-9   # 4400/4000, 4500/5000, 3300/3000
    cur = d["curve"]
    assert cur["copy"][0] == 0 and cur["parent"][0] == 0             # both lines start at 0 % on the copy's first day
    assert abs(cur["parent"][-1] - 0.1) < 1e-9 and abs(cur["copy"][-1] + 0.1) < 1e-9
    assert abs(cur["parent"][1] - 0.025) < 1e-9 and abs(cur["copy"][2] + 0.08) < 1e-9   # T0 + 1h: 2,050; T0 + 2h: 4,600
    with pytest.raises(HTTPException) as e:
        CC.compare(db, "S@15m", now_ms=T0 + 6 * H)                      # not a copy
    assert e.value.status_code == 404
    assert open(db, "rb").read() == before                            # read-only


def test_copy_card_rows_and_wiring():
    out = _node("const C = await import('{base}/account-copy.js');", """
      const d = {count_only: false, parent: {trades: 2, win_rate: 1, ret: 0.1, mean_roe: 0.1, fees_share: 0.005, funding_share: 0.001, liquidations: 0},
                 copy: {trades: 2, win_rate: 0, ret: -0.1, mean_roe: -0.05, fees_share: 0.004, funding_share: 0.001, liquidations: 1}};
      console.log(JSON.stringify({rows: C.copyRows(d), ds: C.copyRows({...d, count_only: true}).map((r) => r.k)}));""")
    ks = [r["k"] for r in out["rows"]]
    assert ks[0] == "기간 수익률" and "거래당 ROE (평균)" in ks and "수수료 (시작 잔고 대비)" in ks
    assert out["rows"][0]["parent"] == "+10.0%" and out["rows"][0]["copy"] == "−10.0%"
    assert out["ds"] == ["거래 (이 기간에 끝난 것)", "이긴 비율", "강제청산"]       # a DeepSeek copy: counts only
    src = _read("account-copy.js")
    assert "/api/v4/copycmp/" in src and "ui.errorBox(e, load)" in src and "ui.smallSample(" in src
    assert 'a.kind === "copy" ? copyCard(ctx, acc.account_id)' in _read("account.js")


# ---------------------------------------------------------------- 손실 거래 <-> 회의
def _agents(path, rounds):
    from paperbot.agents import rooms_db as R
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=T0 - 100 * H)
    for room, trig, data, started in rounds:
        c.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status, decision) VALUES (?,?,?,?,?,?,?)",
                  (room, trig, json.dumps(data), started, started + 600_000, "done", json.dumps({"summary_ko": "🧾 결정: 가설 기록"})))
    c.commit()
    c.close()
    return path


def _ids_of(db, aid):
    import sqlite3
    c = sqlite3.connect(db)
    out = [(r[0], r[1]) for r in c.execute("SELECT id, exit_time FROM trades WHERE account_id = ? ORDER BY id", (aid,))]
    c.close()
    return out


def test_loss_meetings_link_their_trades_both_ways(tmp_path):
    import sqlite3
    from paperbot.dash.more import losslinks as LL
    db = _paper(str(tmp_path / "paper3.db"))
    copy = _ids_of(db, "S@15m~c1")                    # two losing copy trades, exits T0+2h and T0+4h
    ds = _ids_of(db, "D@15m")[0]
    ag = _agents(str(tmp_path / "agents3.db"), [
        ("strat:S", "loss_cluster", {"trade_ids": [copy[0][0], copy[1][0]], "oldest_exit": copy[0][1], "newest_exit": copy[1][1]},
         T0 + 5 * H),
        # an older meeting (before a restore) that stored the same ids for other trades: its window does not match
        ("strat:S", "loss_cluster", {"trade_ids": [copy[0][0]], "oldest_exit": T0 - 50 * H, "newest_exit": T0 - 49 * H}, T0 - 48 * H),
        ("team:ds_structure", "group_loss", {"trade_ids": [ds[0]], "oldest_exit": ds[1], "newest_exit": ds[1]}, T0 + 3 * H),
        ("strat:S", "morning", {"trade_ids": [copy[0][0]]}, T0 + 6 * H),                  # not a loss meeting: ignored
    ])
    a = sqlite3.connect(ag)
    a.row_factory = sqlite3.Row
    rounds = LL.load_rounds(a)
    a.close()
    assert sorted(r["trigger"] for r in rounds.values()) == ["group_loss", "loss_cluster", "loss_cluster"]
    idx = LL.index(rounds)
    p = sqlite3.connect(db)
    p.row_factory = sqlite3.Row
    titles = {"strat:S": "S 방"}
    got = LL.for_trades(rounds, idx, p, [copy[0][0], copy[1][0], 999], titles, {"loss_cluster": "손실 묶음 복기"})
    first = got[str(copy[0][0])]
    assert len(first) == 1 and first[0]["started_ts"] == T0 + 5 * H       # the old meeting's window does not match
    assert first[0]["trigger_ko"] == "손실 묶음 복기" and first[0]["room_title"] == "S 방"
    assert got["999"] == []
    rr = LL.for_rounds(rounds, p, sorted(rounds), titles, {})
    new_id = next(k for k, v in rounds.items() if v["started_ts"] == T0 + 5 * H)
    old_id = next(k for k, v in rounds.items() if v["started_ts"] == T0 - 48 * H)
    ds_id = next(k for k, v in rounds.items() if v["trigger"] == "group_loss")
    assert [t["id"] for t in rr[str(new_id)]["trades"]] == [copy[0][0], copy[1][0]] and rr[str(new_id)]["stored"] == 2
    assert rr[str(old_id)]["trades"] == [] and rr[str(old_id)]["stored"] == 1          # stored, but not these trades
    dst = rr[str(ds_id)]["trades"][0]
    assert dst["count_only"] is True and "pnl" not in dst and "roe" not in dst          # DeepSeek: counted only
    assert rr[str(new_id)]["trades"][0]["pnl"] == -400.0
    p.close()
    # agents3.db that cannot be read is not "no meetings": None, and the route keeps its last index
    broken = sqlite3.connect(":memory:")
    assert LL.load_rounds(broken) is None and LL.load_rounds(None) == {}
    broken.close()
    assert LL._ids("3,a,3,-1,4", 10) == [3, 4]


def test_loss_links_route_and_page_wiring(tmp_path):
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app
    db = _paper(str(tmp_path / "paper3.db"))
    copy = _ids_of(db, "S@15m~c1")
    ag = _agents(str(tmp_path / "agents3.db"), [
        ("strat:S", "loss_cluster", {"trade_ids": [copy[0][0]], "oldest_exit": copy[0][1], "newest_exit": copy[0][1]}, T0 + 5 * H)])
    before = open(db, "rb").read(), open(ag, "rb").read()
    c = TestClient(create_app(db, None, b"s" * 32, agents_db=ag, inbox_db=str(tmp_path / "inbox.db")))
    d = c.get(f"/api/v4/losslinks?trades={copy[0][0]},{copy[1][0]}&rounds=1").json()
    assert d["ready"] is True and len(d["trades"][str(copy[0][0])]) == 1 and d["trades"][str(copy[1][0])] == []
    assert d["rounds"]["1"]["stored"] == 1 and d["rounds"]["1"]["trades"][0]["id"] == copy[0][0]
    assert c.get("/api/v4/losslinks").json() == {"ready": True}
    assert (open(db, "rb").read(), open(ag, "rb").read()) == before          # read-only
    ml = _read("meet-links.js")
    assert "/api/v4/losslinks?" in ml and "never \"회의 없음\"" in ml and '"개수만"' in ml
    assert "tradeMeetSlot(ctx, t)" in _read("account.js") and "tradeMeetSlot(ctx, t)" in _read("replay.js")
    assert "tradeMeetSlot(ctx, t, {nested: true})" in _read("home-live.js")
    assert "LOSS_TRIGGERS.includes(m.trigger) ? roundTradesSlot(ctx, m.round_id)" in _read("digest-board.js")
    assert "LOSS_TRIGGERS.includes(m.meeting) ? roundTradesSlot(ctx, m.round_id)" in _read("rooms-chat.js")
    out = _node("const M = await import('{base}/meet-links.js');",
                "console.log(JSON.stringify([M.nameOf('S5_DONCHIAN_MFI@15m~c1'), M.nameOf('S5_DONCHIAN_MFI@15m')]));")
    assert out[0].endswith("복제 c1") and "~" not in out[0] and "15분" in out[1]


# ---------------------------------------------------------------- 결재함
def _period(start, end, nb, mb, eb, nv, mv, ev):
    arm = lambda n, m, e: {"trades": n, "mean_roe": m, "mean_pnl_equity": e}       # noqa: E731
    return {"start": start, "end": end, "available": True, "baseline": arm(nb, mb, eb), "variant": arm(nv, mv, ev), "diff": mv - mb, "p": 0.001}


def _approvals_world(tmp_path):
    from paperbot.agents import extra_accounts as X
    from paperbot.agents import rooms_db as R
    db = _paper(str(tmp_path / "paper3.db"))
    ag, ib = str(tmp_path / "agents3.db"), str(tmp_path / "inbox.db")
    c = R.open_agents(ag)
    R.ensure_rooms(c, ts=T0 - 100 * H)
    room = "strat:S5_DONCHIAN_MFI"
    rid = c.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, status) VALUES (?,?,?,?,?)",
                    (room, "weekly", "{}", T0, "done")).lastrowid
    R.post(c, room, rid, "weekly", "spec_S5_DONCHIAN_MFI", None, "analysis", "손절을 넓히면 흔들림에 덜 나갑니다.\n둘째 줄",
           {"turn": "specialist", "answer": {"headline": "손절 2.5 ATR가 낫다"}}, ts=T0 + 1)
    R.post(c, room, rid, "weekly", "devils_advocate", None, "challenge", "2기간 차이가 작습니다.",
           {"turn": "challenge", "answer": {"verdict": "needs_test"}}, ts=T0 + 2)
    spec = {"template": "stop_atr", "k": 2.5, "strategy": "S5_DONCHIAN_MFI", "timeframe": "15m"}
    res = {"ok": True, "periods": {"1": _period("2021-08-01", "2024-07-01", 800, -0.03, -0.009, 790, 0.004, 0.0012),
                                   "2": _period("2024-07-01", "2026-09-30", 450, -0.02, -0.006, 440, 0.011, 0.0033),
                                   "3": {"start": "2020-01-01", "end": "2021-08-01", "available": False, "why": "2021년 이전 자료가 없습니다"}}}
    gate = {"pass": True, "n_trials": 3, "reasons": ["① 통과"]}
    tid = R.add_trial(c, room, "S5_DONCHIAN_MFI", "test", spec, rid, ts=T0 + 3)
    R.add_trial_result(c, tid, "passed", {"result": res, "gate": gate, "n_trials": 3}, ts=T0 + 4)
    acc = X.copy_account(R.get_trial(c, tid))
    pid = R.add_proposal(c, room, "S5_DONCHIAN_MFI", tid, {"kind": "copy", "account": acc, "test": spec, "why": "흔들림 손절이 많음",
                                                         "approver": {"approve": True, "reason": "두 기간 같은 방향"}},
                         gate, "awaiting_owner", ts=T0 + 5)
    R.post(c, room, rid, "weekly", "code", None, "action", f"제안 #{pid}", {"action": "propose_copy", "proposal_id": pid}, ts=T0 + 6)
    old = R.add_proposal(c, room, "S5_DONCHIAN_MFI", tid, {"kind": "copy", "account": acc, "test": spec}, gate, "awaiting_owner",
                         ts=T0 - 50 * H)
    R.set_proposal_status(c, old, "rejected", "owner:두 분", ts=T0 - 49 * H)
    c.close()
    R.open_inbox_rw(ib).close()
    return db, ag, ib, pid, old


def test_approvals_view_shows_the_evidence_and_never_writes(tmp_path):
    from paperbot.dash.app import Rooms
    from paperbot.dash.more import approvals as AP
    db, ag, ib, pid, old = _approvals_world(tmp_path)
    before = [open(p, "rb").read() for p in (db, ag)]
    rooms = Rooms(ag, ib, paper_db=db)
    v = AP.view(rooms, db, now_ms=T0 + 10 * H)
    assert v["ready"] is True and [c["id"] for c in v["waiting"]] == [pid] and not v["decided"]
    w = v["waiting"][0]
    assert w["rule_ko"] == "손절 2.5 ATR" and w["parent"] == "S5_DONCHIAN_MFI@15m" and w["why"] == "흔들림 손절이 많음"
    per = w["periods"]
    assert [p["label"] for p in per] == ["1기간 (2021-08~2024-06)", "2기간 (2024-07~2026-09)", "3기간 (2020-01~2021-07)"]
    assert per[0]["arms"][0] == {"label": "원본", "trades": 800, "mean_roe": -0.03, "pnl_equity": -0.009}
    assert per[0]["arms"][1]["label"] == "바꾼 것" and per[2]["available"] is False
    vs = w["voices"]
    assert [x["stance"] for x in vs] == ["제안", "시험 더 필요", "승인관 찬성"]          # the proposer, the challenge, the approver
    assert vs[0]["text"] == "손절 2.5 ATR가 낫다" and vs[1]["tone"] == "against"
    assert [c["id"] for c in v["past"]] == [old] and v["past"][0]["decider_ko"] == "두 분"
    per = v["period"]
    assert per["owner_ok_days"] == 60 and per["observe_until"] == per["start"] + 21 * 86_400_000
    assert per["first_owner_decision_ts"] is None
    assert [open(p, "rb").read() for p in (db, ag)] == before                       # read-only
    assert AP._month_before("2024-07-01") == "2024-06" and AP._month_before("2021-01-01") == "2020-12"


def test_approvals_route_follows_an_owner_click_through_the_existing_decide(tmp_path):
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app
    db, ag, ib, pid, _old = _approvals_world(tmp_path)
    c = TestClient(create_app(db, None, b"s" * 32, agents_db=ag, inbox_db=ib))
    assert [x["id"] for x in c.get("/api/v4/approvals").json()["waiting"]] == [pid]
    r = c.post(f"/api/proposals/{pid}/decide", json={"decision": "approve"}, headers={"origin": "http://testserver"})
    assert r.status_code == 200, r.text
    d = c.get("/api/v4/approvals").json()                          # not the cached answer: the click moved it at once
    assert d["waiting"] == [] and [x["id"] for x in d["decided"]] == [pid]
    assert d["decided"][0]["owner_decision"]["decision"] == "approve" and d["period"]["first_owner_decision_ts"]


def test_inbox_page_words_and_one_way_to_approve():
    out = _node("const I = await import('{base}/inbox.js'); const C = await import('{base}/inbox-card.js'); const G = await import('{base}/inbox-guide.js');", """
      const D = 86400000, p = {start: 0, observe_until: 21 * D, owner_ok_until: 60 * D, first_owner_decision_ts: null};
      console.log(JSON.stringify({keys: [I.periodLine(p, 5 * D).key, I.periodLine(p, 30 * D).key, I.periodLine(p, 70 * D).key, I.periodLine(null).key],
        guide: [G.guideShows(p, 19.5 * D, 0), G.guideShows(p, 20.5 * D, 0), G.guideShows(p, 30 * D, 0), G.guideShows({...p, first_owner_decision_ts: 1}, 30 * D, 0),
                G.guideShows(p, 30 * D, 1), G.guideShows(p, 61 * D, 0)],
        title: [C.titleOf({kind: "copy", rule_ko: "손절 2.5 ATR"}), C.titleOf({kind: "newlab", title_ko: "RSI 되돌림"})],
        bar: C.bar({kind: "copy", gate: {n_trials: 4}}), fx: C.effects({kind: "copy", parent: "S@15m", rule_ko: "손절 2.5 ATR", gate: {n_trials: 4}, runtime_ready: false}, p)}));""")
    assert out["keys"] == ["observe", "owner", "after", None]
    assert out["guide"] == [False, True, True, False, False, False]      # from the day before, until the first click / 닫기
    assert out["title"] == ["손절 2.5 ATR", "RSI 되돌림"] and out["bar"]["n"] == 4 and abs(out["bar"]["alpha"] - 0.0125) < 1e-12
    assert any("한 번 더 승인" in x for x in out["fx"]["yes"]) and out["fx"]["no"][0].startswith("대기로 남고")
    card = _read("inbox-card.js")
    assert card.count("ctx.post(") == 1 and "`/api/proposals/${encodeURIComponent(c.id)}/decide`" in card   # the existing route only
    for name in ("inbox.js", "inbox-guide.js", "account-why.js", "account-copy.js", "meet-links.js", "rooms-evidence.js"):
        assert "ctx.post(" not in _read(name), name
    routes = _read("routes.js", os.path.join(V4, "core"))
    assert 'inbox: {ko: "결재함", group: "agents", title: "결재함", hidden: true}' in routes
    bell = _read("bell.js", os.path.join(V4, "core"))
    assert 'href: href("inbox")' in bell and "bell-pop" not in bell
    assert 'href: ctx.href("inbox", null, {p: p.id})' in _read("rooms-side.js") and "inboxGuide(ctx)" in _read("home.js")


# ---------------------------------------------------------------- review fixes (adversarial pass)
def test_approvals_lists_an_approved_proposal_the_runner_waits_to_be_approved_again(tmp_path):
    """The room's '다시 승인' (runner refusal stale_ok / owner_click_missing) is in the 결재함 too, through the same decide."""
    from fastapi.testclient import TestClient
    from paperbot.agents import extra_accounts as X
    from paperbot.agents import rooms_db as R
    from paperbot.dash.app import create_app
    from paperbot.store3 import Store3
    db, ag, ib, pid, _old = _approvals_world(tmp_path)
    c = R.open_agents(ag)
    trial = c.execute("SELECT trial_id FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
    acc = X.copy_account(R.get_trial(c, trial))
    ts = T0 + 7
    again = R.add_proposal(c, "strat:S5_DONCHIAN_MFI", "S5_DONCHIAN_MFI", trial, {"kind": "copy", "account": acc, "test": acc["rule"]},
                           {"pass": True, "n_trials": 3, "reasons": ["① 통과"]}, "awaiting_owner", ts=ts)
    R.set_proposal_status(c, again, "approved", "owner:두 분", ts=ts + 1)
    c.close()
    st = Store3(db)
    st.put_state("extras", T0, {"v": X.V, "refused": {str(again): {"code": "stale_ok", "proposal_ts": ts, "since": ts + 2}}})
    st.commit()
    st.conn.close()
    cl = TestClient(create_app(db, None, b"s" * 32, agents_db=ag, inbox_db=ib))
    d = cl.get("/api/v4/approvals").json()
    got = {x["id"]: x for x in d["waiting"]}
    assert set(got) == {pid, again} and got[again]["again"] is True and got[pid]["again"] is False
    assert got[again]["periods"] and again not in [x["id"] for x in d["past"]]
    r = cl.post(f"/api/proposals/{again}/decide", json={"decision": "approve"}, headers={"origin": "http://testserver"})
    assert r.status_code == 200, r.text                              # the existing route's own 'again' rule took it
    d = cl.get("/api/v4/approvals").json()
    assert again not in [x["id"] for x in d["waiting"]]              # clicked again after the refusal: the runner's turn now
    assert [x["id"] for x in d["decided"]] == [again] and d["decided"][0]["again_sent"] is True
    card = _read("inbox-card.js")
    assert '"다시 승인"' in card and '"거절로 바꾸기"' in card and card.count("ctx.post(") == 1


def test_review_fixes_bars_colours_guide_and_counts():
    out = _node("const A = await import('{base}/analysis.js'); const G = await import('{base}/inbox-guide.js'); const E = await import('{base}/rooms-evidence.js');", """
      const acc = (n) => ({kind: "strategy", trades: n, timeframe: "15m"});
      const board = {accounts: Array.from({length: 287}, () => acc(25)).concat([acc(3)])};       // 287 / 288 done
      const syn = {accounts: Array.from({length: 4}, () => acc(9))};                               // average 9 >= 5
      const D = 86400000, p = {start: 0, observe_until: 21 * D, owner_ok_until: 60 * D, first_owner_decision_ts: null};
      const groups = [{claim: "a", items: [{name: "x", path: "losses.n"}, {name: "y", path: "board.today.trades"}]},
                      {claim: "b", items: [{name: "x", path: "losses.n"}]}];
      console.log(JSON.stringify({risk: A.waitBars("risk", {}, "core", board)[0].share,
        syn: A.waitBars("synergy", {min_trades: 5, waiting: true}, "core", syn)[0].share,
        guide: [G.guideShows(p, 21 * D - 9 * 3600000 - D - 1, 0), G.guideShows(p, 21 * D - 9 * 3600000 - D, 0)],
        evn: E.evidenceCount(groups)}));""")
    assert out["risk"] <= 0.99 and out["syn"] <= 0.99           # not full: never "100%" while the view still waits
    assert out["guide"] == [False, True]                          # from 00:00 KST of the day before (not that time of day)
    assert out["evn"] == 2                                        # a source two claims share counts once
    cp = _read("account-copy.js")
    assert 'h("b", {class: "num"}, pp(d.diff))' in cp and "ui.refNote(null" in cp   # the copy − parent gap: no up / down colour
    assert "나중에 시작한 복제 계좌라 순위표에서는 동전 봇과 견주지 않습니다" in _read("account.js")
    grid, kit = _read("grid.js"), _read("grid-kit.js")
    assert 'local.get("grid-color-v", 0) !== 2' in grid and 'st.color === "vs") { st.color = "own"' in grid
    assert '{mode: "own", vsMark: !ds, href: ctx.href("account", a.id), i}' in kit and 'const mode = ds ? "own" : "vs"' not in kit
    assert "CSS.escape(String(p))" in _read("inbox.js")
