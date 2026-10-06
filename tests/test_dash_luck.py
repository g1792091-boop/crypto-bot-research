"""luck-calc: 운 vs 실력 (/api/v4/luck, paperbot/dash/more/luck.py; screens/luck-kit.js on 분석, 홈 and 판정).

The luck math against brute force and against simulated nulls (nothing real -> about the luck number passes), the
sequential lab rule (p < 0.05 / test number), the verdict lines, the day-0 states (no database, no file: 준비 중; before
the 30-day verdict: 판정 전 and never a pass), the agents' ledgers on a tiny synthetic agents3.db / debate.db, the
5-year files (the real research summaries, tiny synthetic dash/data JSON), the route, and the page in node."""
import itertools
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import luck_world as LW  # noqa: E402
from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.more import luck as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")


def _read(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as f:
        return f.read()


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


# ---------------------------------------------------------------- the math
def test_tails_match_brute_force():
    ps = [0.05, 0.025, 0.3, 0.5, 0.01]
    for k in range(0, 7):
        brute = sum(np.prod([p if b else 1 - p for p, b in zip(ps, bits)])
                    for bits in itertools.product((0, 1), repeat=len(ps)) if sum(bits) >= k)
        assert L.pb_tail(ps, k) == pytest.approx(brute, abs=1e-12)
    assert L.binom_tail(20, 15, 0.5) == pytest.approx(0.020695, abs=1e-6)      # the page's coin example
    assert L.poisson_tail(0.05, 1) == pytest.approx(1 - np.exp(-0.05))
    assert L.poisson_tail(0.0, 1) == 0.0 and L.poisson_tail(3.0, 0) == 1.0
    ex = L.example()
    assert ex["people"] == 100 and ex["flips"] == 20 and ex["hit"] == 15 and ex["expected"] == pytest.approx(2.07, abs=0.01)


def test_harmonic_luck_is_what_the_sequential_rule_passes_on_pure_noise():
    """The lab: test i passes at p < 0.05 / i. On uniform p-values (nothing real) the mean number of passes over many
    runs equals the sum 0.05 / i (the luck number the page shows)."""
    n = 40
    assert L.harmonic_luck(1) == pytest.approx(0.05) and L.harmonic_luck(0) == 0.0
    assert L.harmonic_luck(3) == pytest.approx(0.05 * (1 + 1 / 2 + 1 / 3))
    rng = np.random.default_rng(1)
    p = rng.random((40_000, n))
    passes = (p < 0.05 / np.arange(1, n + 1)).sum(axis=1)
    assert passes.mean() == pytest.approx(L.harmonic_luck(n), rel=0.05)
    assert np.mean(passes >= 1) == pytest.approx(L.pb_tail([0.05 / i for i in range(1, n + 1)], 1), abs=0.01)


def test_bh_null_any_pass_is_alpha_and_real_effects_pass_more():
    """Benjamini-Hochberg on nothing real: a pass at all happens with chance alpha (Simes), so the simulated luck is
    honest; with real effects mixed in, the passes are far above it (the 'more' verdict)."""
    mean, counts = L.bh_null(108, 0.07)
    c = np.asarray(counts)
    assert len(c) == L.SIMS and np.mean(c >= 1) == pytest.approx(0.07, abs=0.01)
    assert 0.07 <= mean < 0.12
    assert L.bh_null(108, 0.07) is L.bh_null(108, 0.07)                       # cached, same seed -> same numbers
    luck, tail = L.bh_luck([(108, 0.07), (44, 0.025), (1, 0.005)])
    assert tail(0) == 1.0 and 0.08 < tail(1) < 0.12 and tail(5) < 0.01
    assert L.bh_luck([])[0] == 0.0 and L.bh_luck([])[1](1) == 0.0
    # 20 real effects among 108: BH passes most of them, the tail of that under the null is ~0
    from paperbot.checkpoint import bh
    rng = np.random.default_rng(3)
    p = np.concatenate([rng.random(88), rng.random(20) * 1e-5])
    k = int(bh(p, 0.07)[1].sum())
    assert k >= 20 and L.verdict(108, k, tail(k)) == "more"


def test_verdict_lines():
    assert L.verdict(None, None, None) == "preparing"
    assert L.verdict(127, None, None, before=True) == "before"
    assert L.verdict(0, 0, 1.0) == "waiting"
    assert L.verdict(7, 4, 0.3, small=True) == "waiting"
    assert L.verdict(2000, 0, 1.0) == "none"
    assert L.verdict(31, 1, 0.18) == "like_luck"
    assert L.verdict(31, 2, 0.05) == "some"
    assert L.verdict(31, 3, 0.004) == "more"
    assert L.VERDICT_KO["like_luck"] == "통과한 수가 운으로 나올 수와 비슷: 아직 진짜를 찾았다고 할 수 없음"
    assert L.VERDICT_KO["more"] == "운으로 나올 수보다 확실히 많음"


# ---------------------------------------------------------------- day 0: nothing yet
def test_day_zero_without_any_database(tmp_path):
    v = L.luck_view(None, data_dir=str(tmp_path))
    rows = {r["id"]: r for r in v["rows"]}
    assert list(rows) == ["checkpoint", "newlab", "roomtests", "synergy", "staff", "debate", "library", "ds5y",
                          "reel5m", "entry", "indranges", "combo5y"]
    for rid in ("checkpoint", "newlab", "roomtests", "synergy", "staff", "debate", "indranges", "combo5y"):
        assert rows[rid]["verdict"] == "preparing" and rows[rid]["tested"] is None and rows[rid]["passed"] is None, rid
        assert rows[rid]["note"], rid
    assert v["label"] == "설명용, 판정 아님" and v["summary"]["places"] == 12


def test_the_research_summaries_are_read_as_they_are():
    v = L.luck_view(None)
    rows = {r["id"]: r for r in v["rows"]}
    with open(os.path.join(ROOT, "research", "library", "out", "summary.json")) as f:
        a = json.load(f)
    with open(os.path.join(ROOT, "research", "library", "out_b", "summary.json")) as f:
        b = json.load(f)
    assert rows["library"]["tested"] == a["configs"] + b["configs"]
    assert rows["library"]["passed"] == a["stage3"] + b["stage3"]
    assert rows["library"]["luck"] == pytest.approx(0.10)                     # one top-30 carry-over per run
    with open(os.path.join(ROOT, "research", "deepseek200", "out", "summary.json")) as f:
        ds = json.load(f)
    assert rows["ds5y"]["tested"] == ds["configs"] and rows["ds5y"]["passed"] == ds["stage3"]
    assert rows["ds5y"]["counts_only"] is True
    assert not any(re.search(r"pnl|roe|usd|money|equity|wallet", k, re.I) for k in _keys(rows["ds5y"]))
    assert rows["entry"]["tested"] == 290 + 410 + 1680 + 580 and rows["entry"]["passed"] == 0
    assert rows["entry"]["luck"] is None and rows["entry"]["verdict"] == "none"


def test_dash_data_files_when_they_exist_and_when_not(tmp_path):
    d = str(tmp_path)
    assert L.indranges_row(os.path.join(d, "indranges.json"))["verdict"] == "preparing"
    assert L.combo5y_row(os.path.join(d, "combo5y.json"))["verdict"] == "preparing"
    with open(os.path.join(d, "indranges.json"), "w") as f:
        json.dump({"rules": {"tests": 60, "passed": 9, "better": 5, "worse": 4, "fdr": 0.05}}, f)
    with open(os.path.join(d, "combo5y.json"), "w") as f:
        json.dump({"merged": {"trials": 90, "tested": 50, "bh_pass": 1, "both_pass": 0, "fdr": 0.05}}, f)
    ir, cr = L.indranges_row(os.path.join(d, "indranges.json")), L.combo5y_row(os.path.join(d, "combo5y.json"))
    assert ir["tested"] == 60 and ir["passed"] == 9 and ir["verdict"] == "more" and ir["luck"] < 0.1
    assert "더 좋음 5" in ir["passed_ko"] and "더 나쁨 4" in ir["passed_ko"] and "돈을 번다는 뜻은 아닙니다" in ir["note"]
    assert cr["tested"] == 50 and cr["passed"] == 0 and cr["verdict"] == "none" and "보정만 통과 1개" in cr["passed_ko"]
    with open(os.path.join(d, "combo5y.json"), "w") as f:
        f.write("{not json")
    assert L.combo5y_row(os.path.join(d, "combo5y.json"))["verdict"] == "preparing"


# ---------------------------------------------------------------- the run's own records
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from anasyn_world import build
    d = tmp_path_factory.mktemp("luck")
    db = str(d / "paper3.db")
    info = build(db, days=30)
    ag = LW.make_agents(str(d / "agents3.db"), newlab=["failed"] * 30 + ["passed"],
                        tests=[("strat:A", "failed"), ("strat:A", "described"), ("strat:B", "passed")],
                        hyps=[True] * 4 + [False] * 3 + [None] * 2)
    deb = LW.make_debate(str(d / "debate" / "debate.db"), hits=[True] * 9 + [False] * 4)
    return {"dir": d, "db": db, "agents": ag, "debate": deb, **info}


def test_checkpoint_before_the_verdict_never_passes(world):
    from paperbot import checkpoint as CK
    r = L.checkpoint_row(world["db"], str(world["dir"] / "checkpoint.db"))
    c = sqlite3.connect(world["db"])
    want = sum(1 for kind, tf in c.execute("SELECT kind, timeframe FROM accounts")
               if kind in ("strategy", "ds200", "reel")
               and tf in CK.JUDGED_BY_FAMILY[CK.account_family(kind, None)])
    c.close()
    assert r["tested"] == want > 0 and r["verdict"] == "before" and r["passed"] is None and r["passed_ko"] == "판정 전"
    assert r["ready"] is False and r["first_verdict_ts"] and 0.05 < r["luck"] < 0.2
    assert r["plain"] == pytest.approx(want * 0.05, abs=0.01)
    assert sum(f["accounts"] for f in r["families"]) == want
    assert "p" not in r and "q" not in r


def test_checkpoint_after_the_verdict_reads_its_own_numbers(tmp_path):
    from paperbot import checkpoint as CK
    out = str(tmp_path / "checkpoint.db")
    CK.open_out(out).close()
    v = {"date": "2026-11-04", "tested": 120, "luck_passed": 6, "lucky_expected": 0.42, "lucky_if_uncorrected": 8.4,
         "families": [{"group": "core", "alpha": 0.07, "tested": 100, "luck_passed": 6},
                      {"group": "ds200", "alpha": 0.025, "tested": 20, "luck_passed": 0}]}
    c = sqlite3.connect(out)
    c.execute("INSERT INTO verdicts (date, ts, snapshot_sha256, data) VALUES (?,?,?,?)", ("2026-11-04", 1, "x", json.dumps(v)))
    c.commit()
    c.close()
    r = L.checkpoint_row(None, out)
    assert r["ready"] is True and r["tested"] == 120 and r["passed"] == 6 and r["verdict"] == "more"
    assert "많아야 0.4개" in r["passed_ko"] and r["uncorrected"] == 8.4


def test_agents_ledgers(world):
    rows = {r["id"]: r for r in L.ledger_rows(world["agents"])}
    lab = rows["newlab"]
    assert lab["tested"] == 31 and lab["passed"] == 1
    assert lab["luck"] == pytest.approx(L.harmonic_luck(31), abs=1e-3) and lab["verdict"] == "like_luck"
    rt = rows["roomtests"]
    # room A: test 1 (p < 0.05), test 2 described (cannot pass, still counts in A's divisor); room B: test 1
    assert rt["tested"] == 3 and rt["passed"] == 1 and rt["luck"] == pytest.approx(0.10)
    assert rt["tail"] == pytest.approx(1 - 0.95 * 0.95, abs=1e-4) and rt["verdict"] == "some"
    st = rows["staff"]
    assert st["tested"] == 7 and st["passed"] == 4 and st["luck"] == 3.5 and st["verdict"] == "waiting" and st["need"] == 10
    empty = {r["id"]: r for r in L.ledger_rows(LW.make_agents(str(world["dir"] / "empty_agents.db")))}
    assert empty["newlab"]["tested"] == 0 and empty["newlab"]["verdict"] == "waiting"
    assert empty["staff"]["tested"] == 0 and empty["staff"]["verdict"] == "waiting"


def test_debate_record_against_chance(world, tmp_path):
    r = L.debate_row(world["debate"])
    assert r["tested"] == 13 and r["passed"] == 9 and r["luck"] == pytest.approx(6.5)
    assert r["tail"] == pytest.approx(L.binom_tail(13, 9, 0.5), abs=1e-4) and r["verdict"] == "like_luck" and not r["note"]
    few = L.debate_row(LW.make_debate(str(tmp_path / "d.db"), hits=[True] * 5))
    assert few["verdict"] == "waiting" and few["note"]
    easy = L.debate_row(LW.make_debate(str(tmp_path / "e.db"), hits=[True] * 12, base_rate=0.9))
    assert easy["tested"] == 0 and easy["verdict"] == "waiting"           # easy claims are left out by debate_grade


def test_synergy_row_from_the_analysis_answer():
    wait = L.synergy_row({"units": 36, "days": 3, "top": [], "waiting": True, "small": True})
    assert wait["verdict"] == "waiting" and wait["passed"] is None and wait["tested"] > 10_000
    hit = L.synergy_row({"units": 36, "days": 30, "shuffled_days": {"runs": 20, "rank_p": 0.048, "real_beats_share": 1.0}})
    assert hit["passed"] == 1 and hit["verdict"] == "some"                 # one comparison of a maximum: never 'more'
    miss = L.synergy_row({"units": 36, "days": 30, "shuffled_days": {"runs": 20, "rank_p": 0.4, "real_beats_share": 0.6}})
    assert miss["passed"] == 0 and miss["verdict"] == "none"
    assert L.synergy_row(None)["verdict"] == "preparing"


def test_whole_view_on_the_world(world):
    from paperbot.dash.analysis import synergy_view
    syn = synergy_view(world["db"], world["now"])
    v = L.luck_view(world["db"], agents_db=world["agents"], debate_db=world["debate"], syn=syn,
                    checkpoint_db=str(world["dir"] / "none.db"))
    rows = {r["id"]: r for r in v["rows"]}
    assert rows["checkpoint"]["verdict"] == "before" and rows["synergy"]["tested"] > 0
    assert v["summary"]["with_data"] >= 9
    json.dumps(v, allow_nan=False)


# ---------------------------------------------------------------- the route
def test_route_registered_and_answers(world):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    assert "luck" in MORE.MODULES
    app = fastapi.FastAPI()
    done = MORE.register_all(app, data=None, rooms=None, db=world["db"], daily_db=None, agents_db=world["agents"],
                             checkpoint_db=None, candles=None, frames=None)
    assert done["luck"]["routes"] == ["/api/v4/luck"]
    c = TestClient(app)
    d = None
    for _ in range(40):
        d = c.get("/api/v4/luck").json()
        if not d.get("pending"):
            break
        assert d["note"]
        import time
        time.sleep(0.5)
    assert {"rows", "example", "summary", "label", "computed_at"} <= set(d)
    assert {r["id"] for r in d["rows"]} >= {"checkpoint", "newlab", "debate", "library"}


def test_inventory_lists_the_route():
    with open(os.path.join(ROOT, "paperbot", "dash", "static", "v4", "INVENTORY.md"), encoding="utf-8") as f:
        inv = f.read()
    assert "/api/v4/luck" in inv and "운 vs 실력" in inv


# ---------------------------------------------------------------- the page
def _render(expr: str, data: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              f"const K = await import('file://{SCREENS}/luck-kit.js');\n"
              f"const d = {json.dumps(data)};\n"
              "const env = {verdictTs: null, group: 'core', ctx: {href: (n, a) => `#/${n}/${a || ''}`, alive: () => true}, track() {}};\n"
              f"const nodes = {expr};\n"
              "console.log(JSON.stringify(D.walk(nodes)));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_page_words(world, tmp_path):
    with open(os.path.join(tmp_path, "indranges.json"), "w") as f:
        json.dump({"rules": {"tests": 60, "passed": 9, "better": 5, "worse": 4, "fdr": 0.05}}, f)
    v = L.luck_view(world["db"], agents_db=world["agents"], debate_db=world["debate"], data_dir=str(tmp_path),
                    checkpoint_db=str(world["dir"] / "none.db"))
    out = _render("K.luckView(d, env)", json.loads(json.dumps(v)))
    t = out["text"]
    for w in ("운 vs 실력", "왜 중요한가", "지금 실험", "지난 5년 연구", "시험한 수", "운으로 나올 수", "실제 통과",
              "통과 기준", "설명용, 판정 아님", "준비 중", "판정 전", "딥시크는 시험 수와 통과 수만 (돈 숫자 없음)",
              "채점 10개 필요", "운으로 나올 수보다 확실히 많음", "2.07", "기준과 숫자 자세히"):
        assert w in t, w
    assert "USDT" not in t and "p=" not in t and "q=" not in t
    assert sum("lk-dots" in c for c in out["classes"]) == 1
    assert not any(" good" in f" {c}" or " bad" in f" {c}" for c in out["classes"] if "pp" in c)   # neutral pills only
    early = _render("K.luckView(d, env)", json.loads(json.dumps(L.luck_view(None, data_dir=str(world["dir"])))))["text"]
    assert "준비 중" in early and "판정 전" not in early


def test_wiring_tokens_and_text_safety():
    a = _read("analysis.js")
    assert 'import * as L from "./luck-kit.js";' in a
    assert re.search(r'\{id: "luck", label: "운 vs 실력", path: "/api/v4/luck", render: L\.luckView, groups: "any"', a)
    assert 'import {luckMini} from "./luck-kit.js";' in _read("home.js") and "luckMini(ctx" in _read("home.js")
    ck = _read("checkpoint.js")
    assert 'import {luckCheck} from "./luck-kit.js";' in ck and ck.count(", luck") >= 2
    src = _read("luck-kit.js")
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "toLocaleString", "Intl.NumberFormat", "eval("):
        assert bad not in src
    assert "ctx.timeout(() => { if (!dead) ask(); }, RETRY_MS);" in src and "ctx.track(() => { dead = true; });" in src
    css = _read("luck-kit.css")
    for m in re.finditer(r"font(?:-size)?:\s*([^;}]+)", css):
        val = m.group(1)
        assert "var(--t-" in val, m.group(0)
        assert not re.search(r"\b\d+(\.\d+)?(px|rem|em)\b(?!\s*\))", val.split("var(--t-")[0]), m.group(0)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
