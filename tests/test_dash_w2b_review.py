"""Wave 2 part B review fixes (dashboard only, read-only): the coin flips in the 순위표 list, the seat map's pace, the
signals group table and the power card's wording. The pure helpers run under node; DOM-only parts are checked in the
source."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")


def _src(name: str) -> str:
    with open(os.path.join(SCREENS, name), encoding="utf-8") as fh:
        return fh.read()


def _node(body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = (f"const S = await import('{SCREENS}/home-shared.js'); const K = await import('{SCREENS}/checkpoint-stage.js');\n"
              + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


BOARD = """
const A = (id, kind, tf, ret, extra = {}) => ({account_id: id, kind, timeframe: tf, ret, wallet: 5000 * (1 + ret), trades: 12, ...extra});
const board = {initial: 5000, accounts: [
  A("S1@15m", "strategy", "15m", 0.30), A("S2@15m", "strategy", "15m", -0.10), A("S1@1h", "strategy", "1h", 0.05),
  A("DS01_F3@15m", "ds200", "15m", 0.20), A("DS02_F9@1h", "ds200", "1h", -0.30), A("REEL_H1@5m", "reel", "5m", 0.01),
  A("RANDOM_1@15m", "random", "15m", 0.10), A("RANDOM_2@15m", "random", "15m", 0.00), A("RANDOM_3@15m", "random", "15m", -0.20),
  A("RANDOM_1@1h", "random", "1h", 0.40), A("RANDOM_1@5m", "random", "5m", 0.02)]};
const rowsOf = (kinds) => board.accounts.filter((a) => kinds.includes(a.kind)).sort((x, y) => y.ret - x.ret)
  .map((a, i) => ({...a, _rk: i + 1}));
"""


def test_coin_flips_sit_at_their_real_place_without_a_rank_and_deepseek_gets_one_median_line():
    out = _node(BOARD + """
    const core = S.withFlips(rowsOf(["strategy"]), {group: "core", tf: "all", board});
    const ds = S.withFlips(rowsOf(["ds200"]), {group: "ds", tf: "all", board});
    const m5 = S.withFlips(rowsOf(["reel"]), {group: "m5", tf: "all", board});
    const only15 = S.withFlips(rowsOf(["strategy"]).filter((a) => a.timeframe === "15m"), {group: "core", tf: "15m", board});
    const none = S.withFlips(rowsOf(["random"]), {group: "coin", tf: "all", board});
    const ids = (x) => x.items.map((a) => (a._flip ? "F:" : a._flipMed ? "M:" : "") + a.account_id);
    console.log(JSON.stringify({core: ids(core), coreN: core.n, coreAbove: core.above, flipRk: core.items.filter((a) => a._flip).map((a) => a._rk ?? null),
      ds: ids(ds), dsMed: ds.med, dsAbove: ds.above, m5: ids(m5), m5n: m5.n, only15: ids(only15), none}));""")
    # the 36: the 15m and 1h flips (not the 5m one) between the accounts by 수익률; flips never carry a rank number
    assert out["core"] == ["F:RANDOM_1@1h", "S1@15m", "F:RANDOM_1@15m", "S1@1h", "F:RANDOM_2@15m", "S2@15m", "F:RANDOM_3@15m"]
    assert out["coreN"] == 4 and out["flipRk"] == [None, None, None, None]
    assert out["coreAbove"] == 1                       # S1@15m above the 15m median (0.0); S1@1h below the 1h one (0.4)
    # DeepSeek: one median line of the same-bar flips, no flip next to any DeepSeek account (CONTRACT rule 3)
    assert [x for x in out["ds"] if x.startswith("F:")] == [] and sum(x.startswith("M:") for x in out["ds"]) == 1
    assert out["dsMed"] == pytest.approx(0.05) and out["dsAbove"] == 1
    assert out["m5"] == ["F:RANDOM_1@5m", "REEL_H1@5m"] and out["m5n"] == 1
    assert out["only15"] == ["S1@15m", "F:RANDOM_1@15m", "F:RANDOM_2@15m", "S2@15m", "F:RANDOM_3@15m"]
    assert out["none"] is None                          # the coin tab itself gets no extra rows


def test_seat_pace_starts_on_day_3_and_bust_accounts_are_not_projected():
    out = _node("""
    const D = 86400000, start = 1_800_000_000_000, verdict = start + 30 * D;
    const early = K.pace({start}, verdict, start + 1.5 * D), later = K.pace({start}, verdict, start + 6 * D);
    console.log(JSON.stringify({early: early.show, later: later.show, f: later.factor, p0: K.project(0, later.factor),
      p9: K.project(9, later.factor), none: K.pace({}, verdict, start)}));""")
    assert out["early"] is False and out["later"] is True and out["f"] == pytest.approx(5)
    assert out["p0"] == {"mid": 0, "lo": 0, "hi": 0}
    assert out["p9"]["mid"] == pytest.approx(45) and out["p9"]["lo"] == pytest.approx(30) and out["p9"]["hi"] == pytest.approx(60)
    assert out["none"] is None
    src = _src("checkpoint-stage.js")
    assert "p && p.show && !a.bust ? project(n, p.factor)" in src          # a bust account trades no more


def test_signals_group_table_has_no_extra_row_the_server_never_counts():
    src = _src("signals.js")
    assert 'const SIG_GROUPS = [["core", "기존 36"], ["ds200", "딥시크"], ["reel", "5분봉"], ["flip", "동전 봇"]];' in src
    assert '"extra"' not in src.split("const SIG_GROUPS")[1].split("\n")[0]


def test_power_card_says_the_edge_is_over_the_coin_flips():
    src = _src("checkpoint-stage.js")
    assert "같은 봉 동전 봇보다 거래마다 +5%씩" in src and "진짜 실력 (동전 봇보다, 거래당)" in src
