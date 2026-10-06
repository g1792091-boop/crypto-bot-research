"""Dashboard v4 polish, 대시보드 다듬기 7가지 (INVENTORY.md): the account strip of the same strategy, the meeting digest's
reply bars and filters, the calendar's day links, the glossary and its "?" chips, the long / short coin counts, the
funding rows and the folded alert log. Static checks on the page files plus the pure pieces run in node: links and
query params are wired both ways, DeepSeek shows no money per account, positions and funding are counts only,
identical alerts fold and different texts never do, and the per-viewer storage stays wrapped."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCR = os.path.join(V4, "screens")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + SCR
    script = f"const S = (n) => import('{base}/' + n);\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _between(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


# ---------------------------------------------------------------- 1. 같은 매매법 (account)
def test_account_strip_links_and_deepseek_counts_only():
    js = _read("screens", "account.js")
    strip = _between(js, "function sameStrip(", "// ---------------------------------------------------------------- 참고 box")
    # the two buttons: the strategy page at this timeframe, the strategy's AI room (only when it exists)
    assert '{tf: a.timeframe})' in strip and "규칙·지표 차트 보기" in strip     # + the open position's coin (test_dash_livechart)
    assert "const roomId = `strat:${a.strategy}`;" in strip and 'ctx.href("rooms", roomId)' in strip and "담당 AI 방" in strip
    assert "rooms.rooms.some((r) => r.room_id === roomId)" in strip
    # DeepSeek and the coin flips: the closed-trade count and one 참고 pill, never a return, a wallet or USDT per account
    assert 'const ds = a.kind === "ds200", counts = ds || a.kind === "random";' in strip
    assert 'const val = counts ? `${fmt.int(x.trades || 0)}건` : fmt.pct(r, 1);' in strip
    assert 'counts ? ui.pill("", "ref") : null' in strip and 'counts ? null : ui.note("수익률 = 지금 잔고 ÷ 시작 잔고")' in strip
    # the money caption once for the page (owners 10/06 ~14:00): the line at the bottom, the cards keep short notes
    assert 'ui.assumeLine(["closed", "open"])' in js and "ui.assume(" not in js
    # the strip lives under the profile card and follows the board
    assert "el.replaceChildren(...[backLink(), headSlot, same ? same.el : null," in js   # (nulls filtered: conv-a review)
    assert "if (view.same) view.same.update(b);" in js
    # the routes it links to read those params
    assert "q.tf" in _read("screens", "strategies-detail.js")


def test_account_strip_picks_the_same_strategy_and_kind_in_timeframe_order():
    out = _node("""const m = await S('account.js');
    const A = (id, strategy, kind, tf) => ({account_id: id, strategy, kind, timeframe: tf});
    const b = {accounts: [A('X@4h', 'X', 'strategy', '4h'), A('X@15m', 'X', 'strategy', '15m'), A('C@1h', 'X', 'copy', '1h'),
      A('X@1h', 'X', 'strategy', '1h'), A('Y@1h', 'Y', 'strategy', '1h'), A('X@30m', 'X', 'strategy', '30m')]};
    console.log(JSON.stringify(m.sameOf(b, {strategy: 'X', kind: 'strategy'}).map((a) => a.account_id)));""")
    assert out == ["X@15m", "X@30m", "X@1h", "X@4h"]


# ---------------------------------------------------------------- 2. 회의 요약
def test_digest_reply_bar_and_meeting_filters():
    staff, day, css = _read("screens", "digest-staff.js"), _read("screens", "digest-day.js"), _read("screens", "digest.css")
    assert "reactBar(r)," in staff and "반응 아직 없음" in staff
    for k, tok in (("agree", "--term-cyan"), ("disagree", "--down"), ("add", "--term-yellow")):
        assert f".dg-rbar-l i.{k} {{ background: var({tok}); }}" in css
    assert 'ui.pager({size: 10, empty: "아직 없음"' in day and "결정 난 것만" in day
    assert "pager.set(filterMeetings(st.ms, st.kind, st.decided), keep);" in day
    out = _node("""const s = await S('digest-staff.js'); const d = await S('digest-day.js');
    const ms = [{trigger: 'morning', trigger_ko: '아침 회의', status: 'done'}, {trigger: 'loss_cluster', trigger_ko: '손실 묶음 복기', status: 'no_action'},
      {trigger: 'loss_cluster', trigger_ko: '손실 묶음 복기', status: 'done'}, {trigger: 'tf_split', trigger_ko: '봉 비교 회의', status: 'running'}];
    console.log(JSON.stringify({sh: s.reactShares({agree: 3, disagree: 1, add: 0}), none: s.reactShares({agree: 0}),
      kinds: d.meetingKinds(ms).map((k) => [k.id, k.ko, k.n]), loss: d.filterMeetings(ms, 'loss_cluster', false).length,
      lossDone: d.filterMeetings(ms, 'loss_cluster', true).length, done: d.filterMeetings(ms, '', true).length, empty: d.filterMeetings([], '', true).length}));""")
    assert [(x["k"], x["n"], x["w"]) for x in out["sh"]] == [("agree", 3, 75), ("disagree", 1, 25), ("add", 0, 0)]
    assert out["none"] is None
    assert out["kinds"][0] == ["loss_cluster", "손실 묶음 복기", 2] and len(out["kinds"]) == 3
    assert (out["loss"], out["lossDone"], out["done"], out["empty"]) == (2, 1, 2, 0)


# ---------------------------------------------------------------- 3. 달력 › 그날로 가기
def test_calendar_day_links_and_the_screens_that_read_them():
    cal = _read("screens", "flow-cal.js")
    assert 'ctx.href("story", day)' in cal and "그날 하이라이트" in cal
    assert 'ctx.href("digest", "day", {d: day})' in cal and "그날 회의 결론" in cal
    assert "storyNav.from = location.hash" in cal                 # closing the story comes back to 흐름
    assert cal.count("dayLinks(d.d)") == 2                        # with and without a record that day
    story, day = _read("screens", "story.js"), _read("screens", "digest-day.js")
    assert "day: ctx.params.arg || null" in story and "st.day = p.arg || null" in story
    assert 'query && /^\\d{4}-\\d{2}-\\d{2}$/.test(query.d || "") ? query.d' in day


# ---------------------------------------------------------------- 4. 용어 사전
def test_glossary_terms_query_and_account_chips():
    faq, terms, acct = _read("screens", "faq.js"), _read("screens", "faq-terms.js"), _read("screens", "account.js")
    assert 'termsCard((ctx.params.query || {}).q)' in faq and "terms.focusTerm()" in faq
    assert 'import {termChip, termify} from "./faq-terms.js";' in acct and "termify(walletCard);" in acct
    assert "prof.mo = watchTerms(prof.card.el);" in acct and 'termChip("중앙값")' in acct
    assert 'href("faq", null, {q: id})' in terms
    assert "faq-terms" not in _read("screens", "faq-items.js")
    for css in ("faq.css", "account.css"):
        assert '@import url("faq-terms.css");' in _read("screens", css)
    out = _node("""const t = await S('faq-terms.js');
    console.log(JSON.stringify({ids: t.TERMS.map((x) => x.id), lines: t.TERMS.map((x) => x.lines.length),
      q: ['청산가', 'ROI', 'mdd', '손절', '펀딩', '중앙값', '레버리지', '없는말', ''].map(t.findTerm)}));""")
    assert out["ids"] == ["레버리지", "증거금", "청산가", "손절·잠금", "ROE", "최대 낙폭", "승률", "펀딩비", "중앙값"]
    assert out["lines"] == [2] * 9
    assert out["q"] == ["청산가", "ROE", "최대 낙폭", "손절·잠금", "펀딩비", "중앙값", "레버리지", None, None]
    # the lock numbers come from the rule constants, not typed again
    assert "LADDER.first + LADDER.gap" in terms and "innerHTML" not in terms


# ---------------------------------------------------------------- 5. 코인별 롱·숏 개수
def test_coin_chips_count_sides_and_flag_one_sided_only_with_enough_positions():
    kit, pos = _read("screens", "positions-kit.js"), _read("screens", "positions.js")
    assert "export const SKEW_MIN = 5;\nexport const SKEW_SHARE = 0.8;" in kit
    assert '{label: "코인 고르기", sides}' in pos and "sideCounts(mine)" in pos
    seg = _between(kit, "export function coinSeg(", "\n}\n")
    assert "money" not in seg and "pnl" not in seg and "usdt" not in seg.lower()       # counts only
    out = _node("""const k = await S('positions-kit.js');
    const P = (symbol, side) => ({pos: {symbol, side}});
    const list = [P('BTCUSDT', 1), P('BTCUSDT', 1), P('BTCUSDT', 1), P('BTCUSDT', 1), P('BTCUSDT', -1), P('ETHUSDT', -1), P('ETHUSDT', -1)];
    console.log(JSON.stringify({c: k.sideCounts(list), btc: k.oneSided({long: 4, short: 1}), four: k.oneSided({long: 4, short: 0}),
      nine3: k.oneSided({long: 9, short: 3}), sh: k.oneSided({long: 1, short: 9}), none: k.oneSided(null)}));""")
    assert out["c"] == {"BTCUSDT": {"long": 4, "short": 1}, "ETHUSDT": {"long": 0, "short": 2}}
    assert out["btc"] == "long"                     # 4 of 5 = 80 %: one-sided
    assert out["four"] is None                      # fewer than 5 positions: never flagged
    assert out["nine3"] is None and out["sh"] == "short" and out["none"] is None


# ---------------------------------------------------------------- 6. 펀딩 · 우리 모의 계좌
def test_funding_rows_are_counts_and_open_positions_for_that_coin():
    mk, pos = _read("screens", "market.js"), _read("screens", "positions.js")
    assert 'ctx.href("positions", null, {coin: x.sym})' in mk and "다음 펀딩(${minsLeft(x.T, now)} 뒤)" in mk
    assert "const qCoin = String((ctx.params.query || {}).coin" in pos and "COINS.includes(qCoin) ? qCoin" in pos
    fund = _between(mk, "function renderFund(", "\n  }\n")
    assert "wallet" not in fund and "pnl" not in fund and "margin" not in fund and "USDT" not in fund
    out = _node("""const m = await S('market.js');
    console.log(JSON.stringify({pos: m.fundLine(0.0001, {long: 9, short: 3}), neg: m.fundLine(-0.0001, {long: 2, short: 5}),
      zero: m.fundLine(0, {long: 1, short: 1}), none: m.fundLine(0.0001, {long: 0, short: 0}),
      payOnly: m.fundLine(-0.0001, {long: 0, short: 2}), getOnly: m.fundLine(0.0001, {long: 0, short: 4}),
      m45: m.minsLeft(1000 + 45 * 60000, 1000), h3: m.minsLeft(3 * 3600000 + 5 * 60000, 0), past: m.minsLeft(0, 5000)}));""")
    assert out["pos"] == "우리 모의 계좌 롱 9개는 내고 숏 3개는 받음"
    assert out["neg"] == "우리 모의 계좌 숏 5개는 내고 롱 2개는 받음"
    assert "주고받는 돈 없음" in out["zero"] and out["none"] == "우리 모의 계좌 포지션 없음"
    assert out["payOnly"] == "우리 모의 계좌 숏 2개는 냄 (롱 없음)"           # never "롱 0개는 받음"
    assert out["getOnly"] == "우리 모의 계좌 숏 4개는 받음 (롱 없음)"
    assert (out["m45"], out["h3"], out["past"]) == ("45분", "3시간 5분", "0분")


# ---------------------------------------------------------------- 7. 알림 접기 · 새 알림 줄
def test_alert_grouping_folds_identical_alerts_only():
    out = _node("""const g = await S('alerts-group.js');
    const A = (ts, level, text) => ({ts, level, text, ko: text});
    const rows = [A(100, 'WARN', 'feed late BTC'), A(300, 'WARN', 'feed late BTC'), A(200, 'WARN', 'feed late ETH'),
      A(250, 'CRITICAL', 'feed late BTC'), A(50, 'WARN', 'feed late BTC'), A(400, 'INFO', 'start')];
    const gs = g.groupAlerts(rows);
    const view = (x) => [x.level, x.text, x.n, x.first, x.last, x.items.map((a) => a.ts)];
    const d1 = g.withDivider(gs, 220), d0 = g.withDivider(gs, null), dAll = g.withDivider(gs, 10), dNone = g.withDivider(gs, 999);
    console.log(JSON.stringify({gs: gs.map(view), since: g.newSince(gs, 220),
      d1: d1.rows.map((x) => x.divider ? ['DIV', x.n] : x.text + '/' + x.level), d0: d0.n, d0len: d0.rows.length,
      dAll: [dAll.n, dAll.rows.some((x) => x.divider)], dNone: [dNone.n, dNone.rows.some((x) => x.divider)]}));""")
    assert out["gs"] == [
        ["INFO", "start", 1, 400, 400, [400]],
        ["WARN", "feed late BTC", 3, 50, 300, [300, 100, 50]],          # same level + same text: one row
        ["CRITICAL", "feed late BTC", 1, 250, 250, [250]],              # same text, other level: its own row
        ["WARN", "feed late ETH", 1, 200, 200, [200]],                  # different text: never merged
    ]
    assert out["since"] == {"n": 3, "at": 3}                            # 400, 300, 250 came after 220
    assert out["d1"] == ["start/INFO", "feed late BTC/WARN", "feed late BTC/CRITICAL", ["DIV", 3], "feed late ETH/WARN"]
    assert out["d0"] == 0 and out["d0len"] == 4                         # first visit: no line
    assert out["dAll"] == [6, False]                                    # everything new: no line needed
    assert out["dNone"] == [0, False]


def test_alert_screen_uses_the_groups_and_wrapped_per_viewer_storage():
    js = _read("screens", "alerts.js")
    assert 'import {groupAlerts, withDivider} from "./alerts-group.js";' in js
    assert 'local.get("alerts-seen", null)' in js and 'local.set("alerts-seen", top)' in js
    assert "localStorage" not in js and "localStorage" not in _read("screens", "alerts-group.js")
    dom = _read("core", "dom.js")
    local = _between(dom, "export const local = {", "\n};")
    assert local.count("try {") == 3 and "catch (e)" in local          # storage blocked / private window: no throw
    assert "▲ 여기부터 위로 새 알림" in js and "`×${fmt.int(g.n)}`" in js and "처음 " in js and "마지막 " in js
    assert 'match: (g, q) => !g.divider' in js                           # a search never shows the line
    # a live arrival slides its row in once: every fresh key of the group is used up (some() would leave the rest)
    assert "g.items.filter((a) => fresh.delete(key(a))).length" in js and "g.items.some((a) => fresh.delete" not in js


# ---------------------------------------------------------------- shared rules for the new pieces
def test_new_pieces_follow_the_contract():
    files = ["account.js", "digest-staff.js", "digest-day.js", "flow-cal.js", "faq-terms.js", "faq.js", "positions-kit.js",
             "positions.js", "market.js", "alerts.js", "alerts-group.js"]
    for f in files:
        src = _read("screens", f)
        assert "innerHTML" not in src and "toLocaleString(" not in src, f
        assert not re.search(r"https?://", re.sub(r"//[^\n]*", "", src)), f
    for f in ("account.css", "digest.css", "flow.css", "faq-terms.css", "positions-kit.css", "market.css", "alerts.css"):
        css = re.sub(r"/\*.*?\*/", "", _read("screens", f), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css), f
    inv = _read("INVENTORY.md")
    sec = inv[inv.index("## 대시보드 다듬기 7가지"):]
    for k in range(1, 8):
        assert re.search(rf"^\| {k} \|", sec, re.M), k
    # the files other branches edit tonight are untouched by this work
    for f in ("grid-kit.js", "home.js", "board.js", "strategies-list.js", "strategies-detail.js", "signals.js", "faq-items.js"):
        assert "다듬기 7" not in _read("screens", f), f
