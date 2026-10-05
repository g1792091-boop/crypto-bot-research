"""v4 additions, integration (wave 1 ① and ⑤): home's new order and pieces, the reel's 1:3 card and the profile card at
the top of a strategy page. Static checks on the page files (the fixture screenshots check the look):

- home: story rings at the top, the group race inside the head card (its legend = the lines' right ends, U1), the
  group cards' median lines from the same race answer, the list motion on 상위·하위 with compact one-line rows, the
  5분봉 group showing its 1:3 card, no second full ranked list (순위표 has it), and the owners' phone order.
- the 1:3 card: the reel against its three 5m coin flips (a median and faint lines, never money per flip), the trades
  toward the verdict's own 30-trade floor, the 5-year study line tied to research/reel5m/RESULTS_REEL5M.md, 참고 +
  refNote + assume.
- strategies detail: the profile card on top, the 1:3 card for the reel.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCR = os.path.join(V4, "screens")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def test_home_has_the_new_pieces_in_the_owners_phone_order():
    js, css = _read(SCR, "home.js"), _read(SCR, "home.css")
    for imp in ('import {storyRing} from "./story-kit.js";', 'import {raceParts} from "./flow-kit.js";',
                'import {rowMotion} from "./board-motion.js";', 'import {reelDuel} from "./reel-duel.js";'):
        assert imp in js, imp
    # no second copy of the full ranked list on home (순위표 has it): one link instead
    assert "rankList" not in js and "전체 목록" not in js and 'href("board"' in js
    # phone order: rings 0, head card 1, 오늘 2, 묶음 4, 상위·하위 / 1:3 5, LED 6, 최근 회의 7, 처음이라면 8
    order = {"ring": "home-o0", "hero": "home-o1", "todayCard": "home-o2", "groupSec": "home-o4", "ranksCard": "home-o5",
             "duel": "home-o5", "led": "home-o6", "meetCard": "home-o7", "howCard": "home-o8"}
    for name, cls in order.items():
        assert re.search(rf"\b{name}\b[^\n]*{cls}", js), (name, cls)
    for k in range(9):
        if k != 3:
            assert f'.home-o{k} {{ order: {k}; }}' in css, k
    for kit in ("story-kit.css", "flow-kit.css", "reel-duel.css", "home-shared.css"):
        assert f'@import url("{kit}");' in css


def test_home_race_feeds_the_group_lines_and_the_list_motion_is_compact():
    js, shared = _read(SCR, "home.js"), _read(SCR, "home-shared.js")
    assert "onModel: (m) => { st.race = m; renderSparks(); }" in js
    assert "groups.sparks(Object.fromEntries(m.lanes.map((l) => [l.id, l.v])))" in js
    assert "el.sparks = (series) =>" in shared
    assert "topBottom(ctx, {compact: true})" in js and "rowMo.update(b, st.sel);" in js and "rowMo.note(st.sel)" in js
    # a compact row still says small sample (dimmed + caption + aria) and keeps the bust pill
    assert "small ? \" · 표본 적음\" : \"\"" in shared and 'ui.pill("파산", "bad"' in shared
    assert "흐린 줄" in shared and "표본 적음" in shared
    # numbers that change tint once (real data only: countTo's flash)
    assert 'cls: "gm", flash: true' in shared and 'cls: "tv", flash: true' in js
    # the 5분봉 group shows its 1:3 card in the top / bottom list's place
    assert 'const m5 = st.sel === "m5";' in js and "duel.show(m5);" in js


def test_reel_duel_is_honest():
    js = _read(SCR, "reel-duel.js")
    assert 'acts: [ui.pill("", "ref")]' in js and "ui.refNote(vt," in js and 'ui.assume("closed"' in js
    assert "MIN_TRADES" in js and "진행 상황일 뿐 판정 아님" in js
    # the coin flips: a median and faint lines, never a balance or P&L per flip
    assert "derive.median(x.flips.map(w))" in js and "동전 3개 중앙값" in js
    assert not re.search(r"flips\[\d\]\.wallet|f\.wallet", js)
    # nothing drawn before two real points
    assert "real >= 2" in js and "곡선 수집 전" in js and "지어낸 선은 그리지 않습니다" in js
    # one request for the four lines (cached route), one for the per-trade average
    assert "/api/v4/replay/sparks?ids=" in js and '"/api/trades?group=reel&limit=600"' in js


def test_reel_duel_study_line_matches_the_research_results():
    js = _read(SCR, "reel-duel.js")
    res = _read(ROOT, "research", "reel5m", "RESULTS_REEL5M.md")
    m = re.search(r'export const STUDY_KO = "([^"]+)";', js)
    assert m and m.group(1) == "5년 연구: 비용 전 거의 0 · 비용 뒤 거래당 −0.12% · 사전 등록 시험 40개 설정 중 0개 통과"
    assert "**H1 fails. 0 candidates out of 40 configurations.**" in res
    nets = [float(x) for x in re.findall(r"\| -(0\.\d+)% \|", res)]
    assert nets and all(0.115 <= x <= 0.135 for x in nets)          # every period about −0.12 % per trade after costs
    gross = [float(x) for x in re.findall(r"\| \+(0\.\d+)% \|", res)]
    assert gross and max(gross) < 0.02                               # before costs: almost exactly 0


def test_strategy_detail_shows_the_profile_card_or_the_reels_duel_on_top():
    js = _read(SCR, "strategies-detail.js")
    assert 'import {profileCard} from "./grid-kit.js";' in js and 'import {reelDuel} from "./reel-duel.js";' in js
    assert 'kind === "reel" ? reelDuel(ctx, {wide: true, scope: sc' in js
    assert 'h("div", {class: "strat-detail stack"}, head, top,' in js
    assert '@import url("reel-duel.css");' in _read(SCR, "strategies.css")


def test_series_colours_are_tokens():
    tok = _read(V4, "tokens.css")
    for k in ("--series-core", "--series-ds", "--series-m5", "--series-coin"):
        assert k + ":" in tok, k
    for f in ("flow-kit.css", "reel-duel.css", "home-shared.css"):
        src = re.sub(r"/\*.*?\*/", "", _read(SCR, f), flags=re.S)
        assert "var(--series-" in src, f


def test_story_page_two_names_only_main_groups():
    pages = _read(SCR, "story-pages.js")
    assert "coinTop" not in pages and 'a.group === "ds200" ? ui.pill' not in pages
    assert "딥시크와 동전 봇은 계좌마다 돈으로 보여 주지 않고 묶음 숫자로만 봅니다" in pages
