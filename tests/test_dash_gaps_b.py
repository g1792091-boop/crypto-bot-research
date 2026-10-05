"""Dashboard gap batch B (owners told 10/05: 딥시크 17계열 요약표, 진입선·손절선 은은한 빛, 🔊 한 번 누르면 소리 시작).

- the DeepSeek 17-family summary counts board rows per family (definitions, accounts, trades, win rate, busts), with
  the DeepSeek total and the same-timeframe coin flips as the baseline; it carries NO money field and no pass / fail
  words, it has 표본 적음 and the refNote, and it sits on the strategies list's DeepSeek view (+ a link from the grid);
- the terminal chart's entry / stop lines get a static glow overlay drawn only for real lines (no position, no glow),
  tokens only, a one-shot draw-in only for a line that is new after the first paint;
- one tap on the speaker turns an off sound on (setCfg + unlock) and opens the menu; the sound is still off by default
  until that first tap, a tap that closes the menu never switches it on, and the sounds themselves are unchanged.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _node(script: str, store: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = ""
    if store is not None:
        pre = ("const _ls = new Map(Object.entries(" + json.dumps(store) + "));\n"
               "globalThis.localStorage = {getItem: (k) => _ls.has(k) ? _ls.get(k) : null, setItem: (k, v) => _ls.set(k, String(v)),"
               " removeItem: (k) => _ls.delete(k)}; globalThis._ls = _ls;\n")
    r = subprocess.run([node, "--input-type=module", "-e", pre + script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _code(src: str) -> str:
    """The source without // comments (so the honesty words in comments do not count)."""
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


# ---------------------------------------------------------------------------------------------- (1) 17-family summary
def _acct(i, kind, strategy, tf, **kw):
    a = {"account_id": f"{strategy}@{tf}", "strategy": strategy, "timeframe": tf, "kind": kind, "trades": 0, "wins": 0,
         "losses": 0, "bust": False, "position": None, "wallet": 5000 + i, "pnl": i, "gross_win": 0, "gross_loss": 0}
    a.update(kw)
    return a


BOARD = {"initial": 5000, "accounts": [
    # F1: two definitions, three accounts (one carries its family only in its name), one bust
    _acct(1, "ds200", "F1_RSI_DIV", "15m", group="ds200", family="F1", trades=10, wins=6, losses=4),
    _acct(2, "ds200", "F1_RSI_DIV", "1h", group="ds200", family="F1", trades=5, wins=1, losses=4, bust=True),
    _acct(3, "ds200", "F1_MOM_DIV", "4h", trades=5, wins=3, losses=2),
    # F15: one account with an open position
    _acct(4, "ds200", "F15_OPEN0930", "30m", group="ds200", family="F15", trades=40, wins=20, losses=20,
          position={"symbol": "BTCUSDT", "side": 1}),
    # not DeepSeek: the 36, the reel; coin flips at the DeepSeek timeframes count as the baseline, the 5m ones do not
    _acct(5, "strategy", "S1_EMA_RSI_CHOP", "15m", group="core", trades=99, wins=99),
    _acct(6, "reel", "REEL_H1", "5m", group="reel", trades=50, wins=20),
    _acct(7, "random", "RANDOM_1", "15m", group="flip", trades=8, wins=4, losses=4),
    _acct(8, "random", "RANDOM_2", "4h", group="flip", trades=2, wins=1, losses=1, bust=True),
    _acct(9, "random", "RANDOM_1", "5m", group="flip", trades=70, wins=30, losses=40),
]}


def test_family_stats_count_board_rows_without_money():
    kit = "file://" + os.path.join(V4, "screens", "strategies-dsfam.js")
    out = _node(f"const k = await import('{kit}');\n"
                f"const fs = k.familyStats({json.dumps(BOARD)});\n"
                "const empty = k.familyStats(null);\n"
                "console.log(JSON.stringify({fs, empty, tfs: k.DS_TFS}));")
    fs = out["fs"]
    rows = fs["rows"]
    assert [r["id"] for r in rows] == [f"F{i}" for i in range(1, 18)]          # all 17, in order, even with no account
    f1, f15, f2 = rows[0], rows[14], rows[1]
    assert (f1["defs"], f1["accounts"], f1["trades"], f1["wins"], f1["bust"]) == (2, 3, 20, 10, 1)
    assert f1["rate"] == pytest.approx(0.5)
    assert (f15["defs"], f15["accounts"], f15["trades"], f15["open"]) == (1, 1, 40, 1)
    assert (f2["accounts"], f2["trades"], f2["rate"]) == (0, 0, None)
    tot = fs["total"]
    assert (tot["defs"], tot["accounts"], tot["trades"], tot["wins"], tot["bust"]) == (3, 4, 60, 30, 1)
    coin = fs["coin"]                                                         # 15m + 4h flips; the 5m flip is the reel's
    assert (coin["accounts"], coin["trades"], coin["wins"], coin["bust"]) == (2, 10, 5, 1)
    assert out["tfs"] == ["15m", "30m", "1h", "4h"]
    assert out["empty"]["coin"] is None and out["empty"]["total"]["accounts"] == 0
    # COUNTED only: no money field anywhere in the answer
    money = {"pnl", "wallet", "ret", "gross_win", "gross_loss", "equity", "usdt"}
    for r in rows + [tot, coin]:
        assert not money & set(r), r


def test_family_card_is_honest_and_tokens_only():
    src = _read("screens", "strategies-dsfam.js")
    code = _code(src)
    for bad in ("fmt.money", "fmt.usdt", ".pnl", "wallet", "assume(", "합격", "불합격", "통과", "탈락", "✓", "✕"):
        assert bad not in code, bad
    assert "ui.refNote(" in code and "ui.smallSample(" in code and "pp ref" in code
    assert "innerHTML" not in src and "localStorage" not in src and "setInterval" not in src
    assert "motion.flash(" in code and "was &&" in code                     # a tint only on a real change, never the first paint
    css = _read("screens", "strategies.css")
    part = css[css.index("/* DeepSeek 17-family summary"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d", part)
    assert "@keyframes" not in part and "infinite" not in part


def test_family_summary_is_on_the_deepseek_list_and_linked_from_the_grid():
    lst = _read("screens", "strategies-list.js")
    assert 'import {dsFamilyCard, familyStats, familyLine} from "./strategies-dsfam.js";' in lst
    assert "kids = [famCard.el, dsAllCard];" in lst                          # 딥시크 · 전체 요약: the summary first
    assert 'label: "전체 요약"' in lst and 'q === "all" ? ""' in lst          # ?fam=all opens it
    assert 'if (id === "ds") { v.fam = ""; local.set("strat-fam", ""); }' in lst   # choosing 딥시크 starts there
    assert "famCard.update(st.board)" in lst and "familyLine(" in lst          # repainted with the board, family line
    assert "list.setGroup((params.query || {}).g, (params.query || {}).fam)" in _read("screens", "strategies.js")
    grid = _read("screens", "grid.js")
    assert 'ctx.href("strategies", null, {g: "ds", fam: "all"})' in grid and "딥시크 17계열 요약" in grid


# ---------------------------------------------------------------------------------------------- (2) line glow
def test_terminal_line_glow_follows_real_lines_only():
    js = _read("screens", "terminal-chart.js")
    code = _code(js)
    # one glow per real price line: created in the same loop as the line, dropped with it, cleared on a coin switch
    assert 'const glows = h("div", {class: "term-glows", "aria-hidden": "true"});' in code
    assert "rm(l); lines.pos.delete(k); dropGlow(k);" in code
    assert "[...lines.glow.keys()].forEach(dropGlow); glowSeen = false;" in code
    loop = code[code.index("for (const [k, w] of want) {"):code.index("function drawLevels()")]
    assert "lines.glow.set(k, g)" in loop and "g.el.dataset.tone = w.tone;" in loop
    # placed at the line's own price, hidden off the price range; moved by place() (scroll, zoom, resize, tick)
    pg = code[code.index("function placeGlows()"):code.index("function place()")]
    assert "series.priceToCoordinate(g.price)" in pg and "g.el.hidden = true" in pg
    # drawPos (board / ticker) can run before the chart's first layout: the scale width read must not throw out
    assert 'try { sw = C.chart.priceScale("right").width(); } catch (e) { return; }' in pg
    assert "placeGlows();" in code[code.index("function place()"):code.index("function paintTag(")]
    # motion only for a line that is new after the first paint, through the reduced-motion-aware helper
    assert "const real = glowSeen;" in code and "if (real && !g.el.hidden) motion.drawIn(g.band, 500);" in code
    assert "setInterval" not in code and "requestAnimationFrame(placeGlows" not in code


def test_terminal_glow_css_uses_tokens_and_no_loop():
    css = _read("screens", "terminal.css")
    part = css[css.index("/* gap batch B: a soft glow"):css.index(".term-tip {")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d|\b(black|white)\b", part)
    assert "@keyframes" not in part and "animation" not in part and "infinite" not in part
    assert "var(--ug)" in part and "var(--dg)" in part and "var(--accent-glow)" in part
    assert "pointer-events: none" in part
    tok = _read("tokens.css")
    for k in ("--up-glow", "--down-glow", "--accent-glow"):
        assert tok.count(k + ":") == 2, k                                    # both skins (AI default + 클래식)


# ---------------------------------------------------------------------------------------------- (3) one-tap sound
def test_one_tap_turns_the_sound_on_and_it_is_still_off_by_default():
    core = "file://" + os.path.join(V4, "core")
    # turning the sound on starts its feeds (store polling): a hidden page stub keeps them idle, and the script exits
    # itself once it has printed (the polls' intervals would keep node running)
    out = _node("globalThis.document = {visibilityState: 'hidden', hidden: true, addEventListener() {}, removeEventListener() {}};\n"
                f"const sound = await import('{core}/sound.js');\n"
                "const before = {...sound.cfg};\n"
                "const first = sound.startOnTap();\n"
                "const after = {...sound.cfg};\n"
                "const stored = JSON.parse(globalThis._ls.get('pb4-sound'));\n"
                "const second = sound.startOnTap();\n"
                "sound.setCfg({on: false});\n"
                "const offAgain = sound.cfg.on;\n"
                "process.stdout.write(JSON.stringify({before, first, after, stored, second, offAgain}) + '\\n', () => process.exit(0));",
                store={})
    assert out["before"]["on"] is False                                    # off until the first tap
    assert out["first"] is True and out["after"]["on"] is True and out["stored"]["on"] is True
    assert out["second"] is False                                          # already on: nothing changes
    assert out["after"]["vol"] == 60 and out["after"]["night"] is False and out["offAgain"] is False


def test_speaker_tap_starts_only_when_it_opens_the_menu():
    src = _read("core", "sound.js")
    fn = src[src.index("export function startOnTap()"):]
    fn = fn[:fn.index("\n}\n")]
    assert "if (cfg.on) return false;" in fn and "setCfg({on: true});" in fn and "unlock();" in fn
    click = src[src.index('btn.addEventListener("click"'):]
    click = click[:click.index("});") + 3]
    assert "const opening = pop.hidden;" in click and "if (opening) startOnTap();" in click and "setOpen(opening);" in click
    # the checkbox still turns it on / off; a closing tap never calls startOnTap
    assert 'onBox.addEventListener("change", () => { setCfg({on: onBox.checked}); if (onBox.checked) unlock(); });' in src
    assert "const DEFAULTS = {on: false," in src
