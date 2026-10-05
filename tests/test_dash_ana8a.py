"""Batch ana8A (strategy page, dashboard only):

1. the 5-year card says how it was sized: 'v3 크기 규칙 (모든 신호 50배부터)', never '같은 규칙', plus the one line that ROE
   and lock share depend on leverage and that the fair comparison is net per trade in 1x price % (ROE ÷ leverage);
2. '어떻게 끝났나' (screens/strategies-exits.js): the exit reason (손절 / 잠금 +N% per lock_roe step / 강제청산; the reel:
   손절 / 윗밴드 익절 / 시간), the leverage used, 평일·주말, the funding window and the US open window, ported from
   paperbot/sessions.py (checked here against Python's zoneinfo), with the 5-year reference under it and a day-0 state;
3. '이미 해 본 시험' (screens/strategies-prior.js): /api/profile carries packets3.research_prior; the panel shows the
   entry study (support / resistance, entry numbers, trendlines; not parameters) for the 36 and the DeepSeek-200 / reel
   study for the others, with the study's own conclusion.
"""
import json
import os
import random
import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
NEW = ["strategies-exits.js", "strategies-prior.js"]


def _src(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as f:
        return f.read()


def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", src)


def _node(script):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = (f"const X = await import('file://{SCREENS}/strategies-exits.js');\n"
           f"const P = await import('file://{SCREENS}/strategies-prior.js');\n")
    r = subprocess.run([node, "--input-type=module", "-e", pre + script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- 1. the 5-year label
def test_five_year_card_names_the_v3_sizing_and_the_leverage_caveat():
    det, pan = _src("strategies-detail.js"), _src("strategies-panels.js")
    for s in (det, pan):
        assert "같은 규칙" not in s
        assert "v3 크기 규칙 (모든 신호 50배부터)" in s
    line = re.search(r'"거래당 ROE와 잠금 청산 비율은 레버리지에 따라 달라집니다[^"]*"', pan).group(0)
    assert "30배부터" in line and "1배 가격 %" in line and "ROE ÷ 레버리지" in line
    # DeepSeek / the reel: their card is the price-% research, labelled as such (not the v3 sizing)
    assert 'kind === "strategy" ? "과거 시험 · v3 크기 규칙 (모든 신호 50배부터)" : "과거 연구 · 레버리지 없이 가격 %"' in det
    with open(os.path.join(ROOT, "paperbot", "dash", "static", "strat.js"), encoding="utf-8") as f:
        old = f.read()
    assert "같은 규칙:" not in old and "v3 크기 규칙 (모든 신호 50배부터)" in old


# ---------------------------------------------------------------- 2. wiring (new modules, one import each)
def test_detail_wires_the_two_new_modules_additively():
    det = _src("strategies-detail.js")
    assert 'import {exitsCard} from "./strategies-exits.js";' in det
    assert 'import {priorPanel} from "./strategies-prior.js";' in det
    assert "const exits = exitsCard(ctx, {kind});" in det
    assert re.search(r"splitCard, (vs\.el, )?exits\.el, profCard", det)   # wave 2 ⑨ sits before it after the merge
    assert "exits.trades(v.trades);" in det and "exits.profile(v.profile);" in det
    assert "profEl.append(priorPanel(v.profile, kind));" in det
    for f in NEW:
        code = _code(_src(f))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), f
        assert not re.search(r"\b(rgba?|hsla?)\(\s*\d", code), f
        assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|DOMParser|\beval\(|toLocaleString|Intl\.", code), f
        assert re.findall(r'from "([^"]+)"', code) == ["../core/pb.js"], f
        # descriptive only: no pass / fail marks, no p-values
        assert not re.search(r"합격|불합격|✓|✕|p12|p값|p-value", code), f


def test_deepseek_counts_only_and_money_rows_have_the_caption():
    ex = _code(_src("strategies-exits.js"))
    assert 'const money = kind !== "ds200";' in ex
    assert "money ? ui.assume()" in ex
    assert "fmt.money(c.pnl, true)" in ex and ex.index("money ? h(\"b\"") < ex.index("fmt.money(c.pnl, true)")


# ---------------------------------------------------------------- 2. the time windows (sessions.py port)
def _ms_samples():
    rng = random.Random(7)
    lo = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    hi = int(datetime(2028, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    xs = [rng.randrange(lo, hi) for _ in range(3000)]
    # edges: around every DST switch, the funding settlements and the US open, 2024-2027
    for y in range(2024, 2028):
        for m, d in ((3, 1), (11, 1)):
            base = int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
            xs += [base + k * 900_000 for k in range(0, 14 * 96)]
    for k in range(400):
        day = lo + rng.randrange(0, 1400) * 86_400_000
        xs += [day + h * 3_600_000 + s * 1000 for h in (0, 8, 16) for s in (-601, -600, -599, 0, 599, 600, 601)]
        for utc_h, utc_m in ((13, 30), (14, 30)):
            o = day + (utc_h * 60 + utc_m) * 60_000
            xs += [o + s * 1000 for s in (-3601, -3600, -3599, 0, 3599, 3600, 3601)]
    return xs


def test_time_windows_match_sessions_py(tmp_path):
    from paperbot.sessions import time_features
    xs = _ms_samples()
    path = str(tmp_path / "ms.json")
    with open(path, "w") as f:
        json.dump(xs, f)
    got = _node(f"const xs = JSON.parse((await import('node:fs')).readFileSync('{path}', 'utf8'));\n"
                "console.log(JSON.stringify(xs.map((x) => { const w = X.timeWin(x); return [w.weekend, w.funding, w.usOpen]; })));")
    bad = []
    for x, (we, fu, us) in zip(xs, got):
        f = time_features(x)
        if (we, fu, us) != (f["weekend"], "funding" in f["windows"], "us_open" in f["windows"]):
            bad.append((x, (we, fu, us), f))
    assert not bad, bad[:5]
    assert sum(1 for g in got if g[2]) > 100 and sum(1 for g in got if g[1]) > 100   # both windows really exercised


# ---------------------------------------------------------------- 2. the split
def test_exit_split_house_exits_reel_exits_leverage_and_day_zero():
    out = _node("""
const T = (r, lock, lev, pnl, roe, t) => ({exit_reason: r, lock_roe: lock, leverage: lev, pnl, roe, entry_time: t});
const sat = Date.UTC(2026, 9, 3, 3);            // Saturday 12:00 KST
const mon = Date.UTC(2026, 9, 5, 13, 40);       // Monday 09:40 New York (EDT), 22:40 KST
const fund = Date.UTC(2026, 9, 6, 8, 5);        // 5 min after the 08:00 UTC settlement
const house = [T("SL", null, 30, -50, -0.6, sat), T("LOCK", 0.10, 30, 20, 0.10, mon), T("LOCK", 0.15, 50, 30, 0.15, mon),
  T("LOCK", 0.35, 30, 70, 0.35, fund), T("LOCK", 0.30, 20, 60, 0.30, fund), T("LIQ", null, 50, -100, -1, fund),
  T("SL", null, 30, -40, -0.5, fund), {exit_reason: null, pnl: 0}];
const a = X.splitExits(house, "strategy");
const reel = X.splitExits([T("SL", null, 30, -1, -0.1, mon), T("TP", null, 30, 2, 0.2, mon), T("TIME", null, 20, 1, 0.05, mon)], "reel");
const zero = X.splitExits([], "strategy");
const ls = X.lockShareByTf({"15m": house.slice(0, 4), "1h": []});
console.log(JSON.stringify({a, reel, zero, ls}));
""")
    a = out["a"]
    assert a["n"] == 7                                                           # the open row (no exit) is not counted
    assert [r["ko"] for r in a["reason"]] == ["손절", "잠금 +10%", "잠금 +15%", "잠금 +30% 이상", "강제청산"]
    sl = a["reason"][0]
    assert sl["n"] == 2 and sl["losses"] == 2 and abs(sl["share"] - 2 / 7) < 1e-9 and sl["pnl"] == -90
    assert a["reason"][3]["n"] == 2                                              # +30% and +35% share the top row
    assert [r["ko"] for r in a["lev"]] == ["50배", "30배", "20배"]
    assert abs(a["lev"][0]["r1x"] - ((0.15 / 50) + (-1 / 50)) / 2) < 1e-12      # ROE ÷ leverage, the 1x price %
    assert {r["ko"]: r["n"] for r in a["week"]} == {"평일": 6, "주말 (토·일)": 1}
    assert {r["key"]: r["n"] for r in a["funding"]} == {"in": 4, "out": 3}
    assert {r["key"]: r["n"] for r in a["usopen"]} == {"in": 2, "out": 5}
    assert [r["ko"] for r in out["reel"]["reason"]] == ["손절", "윗밴드 익절", "시간 (96봉)"]
    assert out["zero"]["n"] == 0 and out["zero"]["reason"] == []
    assert out["ls"]["15m"] == {"n": 4, "locks": 3, "share": 0.75} and out["ls"]["1h"]["share"] is None
    ex = _src("strategies-exits.js")
    assert "아직 없음 · 끝난 거래가 ${MIN_ROWS}건쯤 쌓이면" in ex                # the day-0 state
    assert "lock_share" in ex and "exit_reason_pct" in ex                      # the two 5-year references
    assert "딥시크 연구는 다른 청산" in ex


# ---------------------------------------------------------------- 3. 이미 해 본 시험
def test_same_sign_reads_the_entry_study_and_skips_nulls_and_5m():
    with open(os.path.join(ROOT, "paperbot", "agents", "research_prior.json"), encoding="utf-8") as f:
        doc = json.load(f)
    s = doc["strategies"]["DOGE"]
    es = {**s["entry_strength"], "features": s["entry_strength"]["features"] + [
        {"tf": "4h", "feature": "x", "label_ko": "널", "spearman_p1_p2_p3": [0.1, 0.2, None], "same_sign_all3": True}]}
    got = _node(f"console.log(JSON.stringify(P.sameSign({json.dumps(es)})));")
    want = sorted((f["tf"], f["label_ko"]) for f in s["entry_strength"]["features"] if f["same_sign_all3"] and f["tf"] != "5m")
    assert sorted((g["tf"], it["ko"]) for g in got for it in g["items"] if it["ko"] != "널") == want
    null = [it for g in got for it in g["items"] if it["ko"] == "널"]
    assert null and abs(null[0]["max"] - 0.2) < 1e-12                          # None is skipped, not read as 0
    pr = _code(_src("strategies-prior.js"))
    assert "parameters" not in pr                                               # parameters are another panel's
    assert "이 매매법은 진입 연구(지지·저항 · 진입 수치 · 추세선) 대상이 아닙니다." in pr
    assert "conclusion_ko" in pr and "설명용" in pr


def test_profile_route_carries_research_prior(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app
    from paperbot.store3 import Store3
    db = str(tmp_path / "p.db")
    Store3(db).close()
    c = TestClient(create_app(db, None, b"x" * 32, candles=lambda s, i, n: []))
    core = c.get("/api/profile/DOGE")
    assert core.status_code == 200
    rp = core.json()["research_prior"]
    assert rp["support_resistance"]["tests"] >= 1 and "entry_strength" in rp and "trendline" in rp
    assert rp["conclusion_ko"] and "live_risk" in core.json()
    from paperbot import ds_profiles
    if ds_profiles.profile("REEL_H1") is not None:
        reel = c.get("/api/profile/REEL_H1").json()
        assert reel["research_prior"]["h1"]["pass"] is False and reel["research_prior"]["configs"] == 40
        per = reel["rows"][0]["periods"]                                         # the reel's 5-year exit mix arrives
        assert set(per["is"]["exit_reason_pct"]) >= {"SL", "TP", "TIME"}
    if ds_profiles.profile("F10_OTE") is not None:
        ds = c.get("/api/profile/F10_OTE").json()["research_prior"]
        assert ds["configs"] == 8 and ds["candidates"] == 0 and len(ds["tests"]) <= 12
    # the rare 36 have NaN cells in their 5-year card: the route answers (null cells), never a 500
    rare = c.get("/api/profile/N14_ICHI_RSI")
    assert rare.status_code == 200 and rare.json()["research_prior"]["entry_strength"]["tests"] == 0
    assert c.get("/api/profile/NOPE").status_code == 404
    det = _src("strategies-exits.js")
    assert 'cls: "strat-o5 strat-howend"' in det                              # not the rule card's .strat-exits box


def test_inventory_has_the_batch_section():
    with open(os.path.join(V4, "INVENTORY.md"), encoding="utf-8") as f:
        inv = f.read()
    sec = inv[re.search(r"(?m)^## (\d+\. )?ana8A", inv).start():]
    for k in ("strategies-exits.js", "strategies-prior.js", "research_prior", "v3 크기 규칙"):
        assert k in sec, k


# ---------------------------------------------------------------- review fixes
def test_review_fixes_deepseek_return_line_neutral_exit_bar_lock_words_and_prior_counts():
    ex = _code(_src("strategies-exits.js"))
    # DeepSeek counts only: the leverage tab's 1x per-trade net (a return) is for the money kinds only
    assert 'money && v.dim === "lev" && rows.some((c) => c.r1x != null)' in ex
    # the exit mix is a share of all trades: a neutral bar, the win / loss bar only for the other tabs
    assert 'share ? h("span", {class: "prog"' in ex and ': h("span", {class: "wl-bar"' in ex
    # the ladder's first lock: armed at net ROE +12%, locks +10% (paperbot/ladder.py, the live settings)
    from paperbot.config import v3_settings
    lad = v3_settings().ladder
    assert (round(lad.first_lock * 100), round((lad.first_lock + lad.trigger_gap) * 100)) == (10, 12)
    assert "첫 잠금 조건(순 ROE +12%에 닿으면 +10% 잠금)" in ex and "잠금선(순 ROE +12%)" not in ex
    pr = _code(_src("strategies-prior.js"))
    # what is left after the three periods comes from the study, never a typed-in 0
    assert "남은 후보는 ${fmt.int(left)}건" in pr and "남은 후보는 0건" not in pr
    assert "srHit.filter((x) => !x.note).length + (Number(es.passed_all3) || 0) + tlHit.length" in pr
    # the reel never falls through to the DeepSeek wording
    assert 'if (kind === "reel") {' in pr and 'kind === "reel" && rp.h1' not in pr
