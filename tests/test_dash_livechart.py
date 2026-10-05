"""The v3 매매법 tab's live chart in v4 (owners 10/06 04:10, two v3 photos): a strategy's chart goes to the coin and
timeframe where it is IN a position, one button per open position puts the chart on it, and the position card and the
account page open the strategy chart on that position (tf + sym), not on the last coin looked at."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCR = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")


def _src(name: str) -> str:
    with open(os.path.join(SCR, name), encoding="utf-8") as fh:
        return fh.read()


def test_detail_follows_the_open_position():
    s = _src("strategies-detail.js")
    i = s.index("if (!bars.TRADE_SYMS.includes(q.sym)) {")
    block = s[i:i + 400]
    assert "a.position && bars.TRADE_SYMS.includes(a.position.symbol)" in block
    assert "held.find((a) => a.timeframe === v.tf) || (q.tf ? null : held[0])" in block      # an asked tf is kept
    assert "v.tf = here.timeframe; v.sym = here.position.symbol;" in block
    assert s.index("if (!bars.TRADE_SYMS.includes(q.sym)) {") < s.index("const symSel =")      # before the picker reads it


def test_live_buttons_sit_above_the_chart_and_follow_the_board():
    s = _src("strategies-detail.js")
    assert 'ui.card({plate: "차트", cls: "strat-o2 strat-chartcard", acts: [symSel, mkBtn]}, liveEl, tfSeg, chart.el)' in s
    assert "renderLive(rows);" in s.split("function renderAccounts()")[1][:200]                 # every board refresh
    assert '"지금 진입 중"' in s and "onclick: () => setChart(a.timeframe, p.symbol)" in s
    assert "지금 진입한 포지션 없음" in s                                                       # says so when flat
    css = open(os.path.join(SCR, "strategies.css"), encoding="utf-8").read()
    assert ".strat-livebtn" in css and "font-size: var(--t-sm)" in css.split(".strat-livebtn {")[1].split("}")[0]


def test_position_card_and_account_open_the_chart_on_the_position():
    pk = _src("positions-kit.js")
    assert 'o.href("strategies", a.strategy, {tf: a.timeframe, sym: pos.symbol})' in pk
    assert 'a.kind === "reel"' in pk.split('"매매법 차트"')[0].rsplit("\n", 1)[-1]
    ac = _src("account.js")
    assert "{tf: a.timeframe, sym: a.position.symbol}" in ac and "진입 중인 차트 보기" in ac
