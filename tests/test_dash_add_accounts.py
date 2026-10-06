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


def _trade(st, aid, entry, exit_t, pnl, roe, reason="SL", fees=2.0, funding=0.5, sym="BTCUSDT"):
    from paperbot.models import TradeRecord
    strat, tf = aid.split("~")[0].split("@")
    st.trade(aid, TradeRecord(strategy_id=strat, symbol=sym, timeframe=tf, side=1, signal_ts=entry - 1, entry_time=entry,
                              entry_price=100.0, exit_time=exit_t, exit_price=99.0, exit_reason=reason, qty=1.0, leverage=30,
                              tier="normal", margin=100.0, stop_price=99.0, tp_price=float("nan"), liq_price=97.0, fees=fees,
                              funding=funding, pnl=pnl, roe=roe, price_move=-0.01, mae_price=99.0, mfe_price=100.0,
                              equity_after=0.0, score=0.0, context={}))


def _paper(path):
    from paperbot.store3 import Store3
    st = Store3(path)
    st.add_account("S@15m", "S", "15m", "strategy", T0 - 100 * H, "v4")
    st.add_account("S@15m~c1", "S", "15m", "copy", T0, "v4", "S@15m", {"v": 1, "rule": {"template": "stop_atr", "k": 2.5},
                                                                       "label_ko": "S 15분 복제 c1"})
    st.add_account("D@15m", "D", "15m", "ds200", T0 - 100 * H, "v4", None, {"group": "x"})
    for k in (1, 2, 3):
        st.add_account(f"RANDOM_{k}@15m", f"RANDOM_{k}", "15m", "random", T0 - 100 * H, "v4")
    st.equity("S@15m", T0 - 100 * H, 5000.0, 0.0)
    st.equity("S@15m", T0 - H, 2000.0, 0.0)          # the parent's balance when the copy starts
    st.equity("S@15m", T0 + 5 * H, 2200.0, 0.0)
    st.equity("S@15m~c1", T0, 5000.0, 0.0)
    st.equity("S@15m~c1", T0 + 5 * H, 4500.0, 0.0)
    for k, (a, b) in enumerate(((4000.0, 4400.0), (5000.0, 4500.0), (3000.0, 3300.0)), 1):
        st.equity(f"RANDOM_{k}@15m", T0 - 2 * H, a, 0.0)
        st.equity(f"RANDOM_{k}@15m", T0 + 5 * H, b, 0.0)
    _trade(st, "S@15m", T0 - 3 * H, T0 - 2 * H, -300.0, -0.3)                       # before the copy: left out
    _trade(st, "S@15m", T0 + H, T0 + 2 * H, 150.0, 0.15, "LOCK", fees=4.0, funding=1.0)
    _trade(st, "S@15m", T0 + 3 * H, T0 + 4 * H, 50.0, 0.05, "LOCK", fees=6.0, funding=1.0)
    _trade(st, "S@15m~c1", T0 + H, T0 + 2 * H, -400.0, -0.08, "SL", fees=10.0, funding=2.0)
    _trade(st, "S@15m~c1", T0 + 3 * H, T0 + 4 * H, -100.0, -0.02, "LIQ", fees=10.0, funding=3.0)
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
    assert p["trades"] == 2 and p["wins"] == 2                       # the trade it entered before the copy existed: out
    assert abs(p["ret"] - (2200 / 2000 - 1)) < 1e-9                  # from ITS balance at the copy's start, not 5,000
    assert abs(c["ret"] - (4500 / 5000 - 1)) < 1e-9 and c["liquidations"] == 1
    assert abs(p["fees_share"] - 10 / 2000) < 1e-9 and abs(c["fees_share"] - 20 / 5000) < 1e-9
    assert abs(p["mean_roe"] - 0.1) < 1e-9 and c["small"] is True
    assert abs(d["diff"] - (c["ret"] - p["ret"])) < 1e-9
    assert d["flips"]["n"] == 3 and abs(d["flips"]["median_ret"] - 0.1) < 1e-9   # 4400/4000, 4500/5000, 3300/3000
    cur = d["curve"]
    assert cur["copy"][0] == 0 and cur["parent"][0] == 0             # both lines start at 0 % on the copy's first day
    assert abs(cur["parent"][-1] - 0.1) < 1e-9 and abs(cur["copy"][-1] + 0.1) < 1e-9
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
    assert out["ds"] == ["거래 (이 기간에 들어간 것)", "이긴 비율", "강제청산"]       # a DeepSeek copy: counts only
    src = _read("account-copy.js")
    assert "/api/v4/copycmp/" in src and "ui.errorBox(e, load)" in src and "ui.smallSample(" in src
    assert 'a.kind === "copy" ? copyCard(ctx, acc.account_id)' in _read("account.js")
