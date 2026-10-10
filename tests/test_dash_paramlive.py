"""커스텀값 실시간 비교 (dash/more/paramlive.py, screens/strategies-paramlive.js, screens/analysis-paramlive.js): the
dashboard's read-only view of the nightly custom-value shadow (paperbot/paramshadow.py) summary.

Checks: GET /api/v4/paramlive sits behind the login; without a summary it is {available: false, none_ko: '아직 첫 계산
전 ...'} (the strategy route too, never a 404 then); with one it carries status, line_ko, the totals, the texts, the
settings and ONE COMPACT cell per strategy x timeframe (no variant rows, no parameter list); GET
/api/v4/paramlive/<strategy> gives that strategy's four cells in timeframe order with every variant row and the
parameters' Korean names (params.PARAM_KO); an unknown name is a 404 once a summary exists; an error.json newer than the
summary adds error_ko / error_at next to the last good data (an older one is ignored); a damaged, non-object or no_run
file and NaN numbers never give a 500; the file is parsed once per mtime and nothing is written; the 분석 view is
registered (기존 36 only), the 매매법 상세 card is added for the 36 only, right after the parameter card; the
paperbot-paramshadow timer is in the 예약 작업 list with its Korean name and its 10:00 KST calendar."""

import json
import os
import re
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import jobs as J  # noqa: E402
from paperbot.dash.more import paramlive as P  # noqa: E402
from paperbot.dash.more.params import PARAM_KO  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
PW = "paramlive horse battery"
SECRET = b"q" * 32
TFS = ("15m", "30m", "1h", "4h")
GEN = 1_791_511_200_000                       # 2026-10-09 02:00 UTC
TEXTS = {"what": "기존 36개 매매법을 숫자 하나만 바꿔 ...", "base": "기본값(재계산) = ...", "parity": "재계산 일치 = ...",
         "luck": "★는 거래 20건 이상이고 ... 우연으로도 최대 약 0.4칸에 ★가 붙을 수 있습니다.", "caution": "참고용입니다. ..."}


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return fh.read()


def _stats(trades, pnl, h1=None):
    return {"trades": trades, "wins": trades // 2, "win_rate": (trades // 2) / trades if trades else None, "pnl": pnl,
            "equity": 5000 + pnl, "max_dd": 0.1, "pnl_h1": pnl / 2 if h1 is None else h1, "pnl_h2": pnl / 2,
            "mean_ret": 0.001 if trades else None, "sd_ret": 0.02 if trades > 1 else None}


def _cell(strategy, tf, params, star_key=None, same_keys=(), small=False):
    base = {**_stats(30, -100.0), "open": tf == "15m", "bust": False}
    variants = []
    for p in params:
        for m in (0.5, 0.75, 1.25, 1.5):
            key = f"{p['name']}x{m:g}"
            same = key in same_keys
            diff = 0.0 if same else round(40.0 * (m - 1) * (1 if p["name"].endswith("len") else -1), 2)
            value = [int(x * m) for x in p["default"]] if isinstance(p["default"], list) else round(p["default"] * m, 3)
            v = {"key": key, "param": p["name"], "mult": m, "value": value, "default": p["default"],
                 "same_as_base": same, "signals": 50, "signals_diff": 0 if same else 7,
                 **{k: x for k, x in _stats(30, -100.0 + diff).items() if k in ("trades", "wins", "win_rate", "pnl", "equity", "max_dd")},
                 "open": False, "bust": False, "diff_pnl": diff}
            if same:
                v.update(luck=None, both_halves=None, star=False)
            else:
                v.update(luck={"small": small, "z": None if small else 0.5, "z_need": 2.7, "luck_pp": None if small else 1.0,
                               "diff_pp": None if small else 0.2, "ratio": None if small else 0.19, "beyond": key == star_key},
                         both_halves=key == star_key, star=key == star_key)
            variants.append(v)
    diffs = [v for v in variants if not v["same_as_base"]]
    best = max(diffs, key=lambda v: v["diff_pnl"]) if diffs else None
    return {"strategy": strategy, "tf": tf, "params": params, "base": base,
            "real": {**_stats(28, -90.0), "open": False}, "parity": {"base_trades": 30, "real_trades": 28, "same": 24, "share": 0.8},
            "k": len(diffs), "variants": variants, "better": sum(1 for v in diffs if v["diff_pnl"] > 0),
            "stars": sum(1 for v in variants if v["star"]),
            "best": {"key": best["key"], "diff_pnl": best["diff_pnl"], "star": best["star"]} if best else None}


def summary(status="ok", nan=False):
    """A small last.json of paramshadow's shape: two of the 36 x the four timeframes."""
    s2 = [{"name": "st_atr_len", "default": 10, "kind": "length"}, {"name": "st_mult", "default": 6.0, "kind": "mult"}]
    n03 = [{"name": "adx_len", "default": 14, "kind": "length"}, {"name": "kst_roc_lens", "default": [10, 15, 20, 30], "kind": "length"}]
    cells = [_cell("S2_ST_ROC", tf, s2, star_key="st_atr_lenx1.5" if tf == "1h" else None,
                   same_keys=("st_multx0.75",) if tf == "4h" else ()) for tf in TFS]
    cells += [_cell("N03_ADX_GC", tf, n03, small=True) for tf in TFS]
    if nan:
        cells[0]["base"]["mean_ret"] = float("nan")
        cells[0]["variants"][0]["luck"]["z"] = float("inf")
    variants = sum(c["k"] for c in cells)
    better = sum(c["better"] for c in cells)
    d = {"version": 1, "status": status, "generated_ms": GEN, "run_start_ms": GEN - 5 * 86_400_000, "through_day": "2026-10-08",
         "days": 4, "days_remaining": 3 if status == "filling" else 0,
         "settings": {"version": "paper-v4", "initial_equity": 5000.0, "taker_fee": 0.0005, "slippage": 0.0002,
                      "leverage_rule": "quality_v1", "stop_atr": 2.0},
         "brackets_src": "test", "multipliers": [0.5, 0.75, 1.25, 1.5], "min_trades": 20, "alpha": 0.05, "tfs": list(TFS),
         "overview": {"cells": len(cells), "variants": variants, "better": better, "stars": 1, "cells_tested": 8,
                      "stars_by_luck": 0.4, "parity": 0.8},
         "cells": cells, "notes": ["BTCUSDT 4h: 차트 봉 40개(필요 61개 이상), 이 구간 신호 없음"], "texts_ko": TEXTS,
         "line_ko": f"커스텀값 그림자 10/8까지 4일: 변형 {variants}개 중 기본값보다 번 것 {better} · ★ 1(우연으로도 최대 0.4) · 기본값 재계산 일치 80%"}
    return d


def _write(folder, name, obj, mtime=None):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def psdir(tmp_path, monkeypatch):
    d = tmp_path / "paramshadow"
    d.mkdir()
    monkeypatch.setenv("PAPERBOT_PARAMSHADOW_DIR", str(d))
    P._CACHE.clear()
    yield str(d)
    P._CACHE.clear()


@pytest.fixture
def client(tmp_path, psdir):
    db = str(tmp_path / "paper3.db")
    Store3(db).close()
    app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], inbox_db=str(tmp_path / "inbox.db"))
    c = TestClient(app)
    assert c.get("/api/v4/paramlive").status_code == 401                     # behind the same login
    assert c.get("/api/v4/paramlive/S2_ST_ROC").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    assert "paramlive" in app.state.more
    return c


# ---------------------------------------------------------------- the routes
def test_missing_file_is_not_available_yet_never_a_404(client, psdir):
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["none_ko"] == "아직 첫 계산 전입니다 (매일 10:00 KST에 계산)"
    assert "cells" not in d and "error_ko" not in d and d["about_ko"] and "판정 아님" in d["label_ko"]
    r = client.get("/api/v4/paramlive/S2_ST_ROC")
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["strategy"] == "S2_ST_ROC"
    assert client.get("/api/v4/paramlive/NOT_ONE").status_code == 200     # nothing to tell a name from yet


def test_overview_is_compact_with_the_jobs_counts(client, psdir):
    s = summary()
    _write(psdir, "last.json", s)
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is True and d["status"] == "ok" and d["line_ko"] == s["line_ko"]
    assert (d["through_day"], d["days"], d["days_remaining"], d["generated_ms"]) == ("2026-10-08", 4, 0, GEN)
    assert d["overview"] == s["overview"] and d["texts_ko"] == TEXTS and d["min_trades"] == 20
    assert d["settings"] == s["settings"] and d["multipliers"] == [0.5, 0.75, 1.25, 1.5] and d["tfs"] == list(TFS)
    assert d["notes"] == s["notes"] and "error_ko" not in d and "error" not in d    # 분석 paints a bare d.error as a failure
    assert len(d["cells"]) == 8
    for c in d["cells"]:
        assert set(c) == {"strategy", "tf", "name_ko", "base", "real", "parity", "k", "better", "stars", "best"}
        assert set(c["base"]) == {"trades", "pnl", "win_rate"} and set(c["real"]) == {"trades", "pnl"}
        assert set(c["parity"]) == {"share"}
    assert "variants" not in json.dumps(d["cells"]) and "params" not in json.dumps(d["cells"])
    src = {(c["strategy"], c["tf"]): c for c in s["cells"]}
    for c in d["cells"]:
        o = src[(c["strategy"], c["tf"])]
        assert (c["k"], c["better"], c["stars"]) == (o["k"], o["better"], o["stars"])
        assert c["base"]["trades"] == o["base"]["trades"] and c["parity"]["share"] == o["parity"]["share"]
    assert sum(c["k"] for c in d["cells"]) == d["overview"]["variants"]
    assert sum(c["better"] for c in d["cells"]) == d["overview"]["better"]
    one = next(c for c in d["cells"] if c["strategy"] == "S2_ST_ROC" and c["tf"] == "1h")
    assert one["name_ko"] == "슈퍼트렌드·ROC" and one["stars"] == 1
    assert one["best"]["param"] and one["best"]["param_ko"] == PARAM_KO[one["best"]["param"]] and one["best"]["mult"]
    assert len(client.get("/api/v4/paramlive").content) < 20_000


def test_strategy_route_gives_full_rows_with_korean_names(client, psdir):
    s = summary(status="filling")
    _write(psdir, "last.json", s)
    d = client.get("/api/v4/paramlive/S2_ST_ROC").json()
    assert d["available"] is True and d["status"] == "filling" and d["days_remaining"] == 3
    assert d["strategy"] == "S2_ST_ROC" and d["name_ko"] == "슈퍼트렌드·ROC" and d["texts_ko"] == TEXTS
    assert d["through_day"] == "2026-10-08" and d["days"] == 4
    assert [c["tf"] for c in d["cells"]] == list(TFS)
    for c in d["cells"]:
        assert len(c["variants"]) == 8 and {"base", "real", "parity", "k", "better", "stars", "best"} <= set(c)
        for p in c["params"]:
            assert p["param_ko"] == PARAM_KO[p["name"]]
        for v in c["variants"]:
            assert v["param_ko"] == PARAM_KO[v["param"]] and "diff_pnl" in v and "same_as_base" in v and "luck" in v
    h1 = d["cells"][2]
    assert [v["key"] for v in h1["variants"] if v["star"]] == ["st_atr_lenx1.5"]
    four = d["cells"][3]
    assert [v["key"] for v in four["variants"] if v["same_as_base"]] == ["st_multx0.75"] and four["k"] == 7
    n03 = client.get("/api/v4/paramlive/N03_ADX_GC").json()
    lens = next(v for v in n03["cells"][0]["variants"] if v["param"] == "kst_roc_lens")
    assert lens["param_ko"] == "KST ROC 길이들" and isinstance(lens["value"], list)
    assert all(v["luck"]["small"] for c in n03["cells"] for v in c["variants"])


def test_unknown_strategy_is_404_once_a_summary_exists(client, psdir):
    _write(psdir, "last.json", summary())
    r = client.get("/api/v4/paramlive/NOT_A_STRATEGY")
    assert r.status_code == 404 and r.json()["detail"] == "그런 매매법이 없습니다"
    assert client.get("/api/v4/paramlive/F9_FVG").status_code == 404           # DeepSeek: not in the shadow


def test_error_json_newer_than_the_summary_is_shown_next_to_the_last_good_data(client, psdir):
    _write(psdir, "last.json", summary())
    err = {"generated_ms": GEN + 86_400_000, "error": "1m bars of 2026-10-09 unavailable: timeout",
           "line_ko": "커스텀값 그림자: 이번 밤 계산 못 함 (1m bars of 2026-10-09 unavailable: timeout)"}
    _write(psdir, "error.json", err)
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is True and d["error_ko"] == err["line_ko"] and d["error_at"] == err["generated_ms"]
    assert len(d["cells"]) == 8 and "error" not in d
    s = client.get("/api/v4/paramlive/S2_ST_ROC").json()
    assert s["error_ko"] == err["line_ko"] and len(s["cells"]) == 4
    # an older failure (the good night after it wrote last.json) is not news
    _write(psdir, "error.json", {**err, "generated_ms": GEN - 86_400_000})
    assert "error_ko" not in client.get("/api/v4/paramlive").json()
    # the very first night failed: no summary, the failure line
    os.remove(os.path.join(psdir, "last.json"))
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["none_ko"].startswith("아직 첫 계산 전") and d["error_ko"] == err["line_ko"]


def test_damaged_no_run_and_nan_files_never_give_a_500(client, psdir):
    _write(psdir, "last.json", '{"status": "ok", "cells": [')                # half-written
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["none_ko"] == P.BAD_KO
    assert client.get("/api/v4/paramlive/S2_ST_ROC").json()["available"] is False
    _write(psdir, "last.json", "[1, 2, 3]")
    assert client.get("/api/v4/paramlive").json()["none_ko"] == P.BAD_KO
    _write(psdir, "last.json", {"status": "ok", "cells": [{"strategy": "S2_ST_ROC", "tf": "1h", "base": 5}], "settings": [1]})
    r = client.get("/api/v4/paramlive")
    assert r.status_code == 200 and r.json()["available"] is False
    _write(psdir, "last.json", {"status": "no_run", "generated_ms": GEN, "line_ko": "커스텀값 그림자: 실행 중인 규칙봇 기록 없음"})
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["status"] == "no_run" and d["none_ko"] == "커스텀값 그림자: 실행 중인 규칙봇 기록 없음"
    _write(psdir, "last.json", json.dumps(summary(nan=True)))                 # json.dumps writes NaN / Infinity
    assert "NaN" in _read(psdir, "last.json")
    r = client.get("/api/v4/paramlive/S2_ST_ROC")
    assert r.status_code == 200
    c = r.json()["cells"][0]
    assert c["base"]["mean_ret"] is None and c["variants"][0]["luck"]["z"] is None
    assert client.get("/api/v4/paramlive").status_code == 200


def test_parsed_once_per_file_change_and_nothing_written(psdir):
    path = _write(psdir, "last.json", summary(), mtime=time.time() - 60)
    before = sorted(os.listdir(psdir))
    a, b = P._summary(psdir), P._summary(psdir)
    assert a[1] is b[1] and P.overview(psdir)["available"] is True
    s = summary(status="filling")
    _write(psdir, "last.json", s)
    assert P.overview(psdir)["status"] == "filling" and P._summary(psdir)[1] is not a[1]
    assert sorted(os.listdir(psdir)) == before == ["last.json"] and os.path.exists(path)
    src = _read(ROOT, "paperbot", "dash", "more", "paramlive.py")
    assert "sqlite3" not in src and not re.search(r"open\([^)]*['\"][wa]", src)
    assert "import paramshadow" not in src and "from ...paramshadow" not in src and "from ... import paramshadow" not in src
    # the default folder is the job's own (deploy/paperbot-paramshadow.service --out)
    assert re.search(r'^DEFAULT_OUT = "%s"$' % re.escape(P.DIR), _read(ROOT, "paperbot", "paramshadow.py"), re.M)
    assert f"--out {P.DIR}" in _read(ROOT, "deploy", "paperbot-paramshadow.service")


# ---------------------------------------------------------------- the pages
def _no_unsafe(js):
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "toFixed(2)"):
        assert bad not in js, bad
    assert "통과" not in js and "합격" not in js                              # a shadow, never a verdict


def test_the_analysis_view_is_registered_for_the_36():
    an = _read(SCREENS, "analysis.js")
    assert 'import {paramlive} from "./analysis-paramlive.js";' in an
    assert re.search(r'\{id: "paramlive", label: "커스텀값 비교", path: "/api/v4/paramlive", render: paramlive, groups: "core",', an)
    css = _read(SCREENS, "analysis.css")
    assert '@import url("analysis-paramlive.css");' in css and '@import url("strategies-paramlive.css");' in css
    js = _read(SCREENS, "analysis-paramlive.js")
    assert "export function paramlive(d, env)" in js and 'ctx.href("strategies", s)' in js
    assert 'ctx.href("strategies", c.strategy, {tf: c.tf})' in js
    assert "변형 ${fmt.int(o.variants || 0)}개 중 기본값보다 번 것" in js and "우연으로도 최대" in js and "재계산 일치" in js
    _no_unsafe(js)
    for p in ("analysis-paramlive.css", "strategies-paramlive.css"):
        c = re.sub(r"/\*.*?\*/", "", _read(SCREENS, p), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", c) and not re.search(r"\brgba?\(\s*\d", c), p
        assert "var(--up)" not in c or p == "strategies-paramlive.css"           # the map's tint is the neutral pair
    assert "--cmp-hi" in _read(SCREENS, "analysis-paramlive.css")
    assert "/api/v4/paramlive" in _read(V4, "INVENTORY.md")


def test_the_detail_card_is_for_the_36_only_after_the_parameter_card():
    detail = _read(SCREENS, "strategies-detail.js")
    assert 'import {paramliveCard} from "./strategies-paramlive.js";' in detail
    lines = detail.splitlines()
    i = next(n for n, x in enumerate(lines) if re.match(r"^\s*paramsCard\(ctx, name, kind, \{after: profCard, scope: sc\}\);", x))
    assert re.match(r'^\s*if \(group === "core" && kind === "strategy"\) paramliveCard\(ctx, name, \{after: profCard, scope: sc, tf: v\.tf\}\);',
                    lines[i + 1])
    js = _read(SCREENS, "strategies-paramlive.js")
    assert "export function paramliveCard(ctx, name" in js and "`/api/v4/paramlive/${encodeURIComponent(name)}`" in js
    assert 'plate: "커스텀값 실시간 비교", sub: "v4 시작부터 · 숫자 하나만 바꾼 그림자 계좌 · 매일 10:00 갱신"' in js
    assert 'cls: "strat-o7 strat-pl"' in js and 'nx.classList.contains("strat-pm")' in js
    for words in ("기본값(재계산)", "실제 계좌", "재계산 일치", "기본값과 신호 같음", "표본 적음", "운 기준선 대비", "채우는 중", "지난 계산 실패",
                  "기본값 대비", "motion.shimmer(", "ui.errorBox(err, load)", "ui.assume()"):
        assert words in js, words
    assert '"luck", "parity", "caution"' in js
    _no_unsafe(js)
    assert '@import url("strategies-paramlive.css");' in _read(SCREENS, "strategies.css")
    css = _read(SCREENS, "strategies-paramlive.css")
    assert "container-type: inline-size" in css and "@container (min-width: 480px)" in css


def test_value_and_tint_helpers_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pl, an = _read(SCREENS, "strategies-paramlive.js"), _read(SCREENS, "analysis-paramlive.js")
    grab = lambda src, n: re.search(r"^export function %s\(.*?^}$" % n, src, re.S | re.M).group(0)[len("export "):]  # noqa: E731
    js = ("const fmt = {num: (x, d) => (x < 0 ? '−' : '') + Math.abs(x).toFixed(d)};\n" + grab(pl, "valueKo") + "\n" + grab(an, "step")
          + "\nconsole.log(JSON.stringify([[10, 6.0, 0.75, 1.125, 0.0075, [5, 8, 10, 15], null].map(valueKo),"
            " [[0, 0], [0, 12], [2, 12], [5, 12], [8, 12], [12, 12]].map(([b, k]) => step(b, k))]));")
    out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=20, check=True).stdout)
    assert out == [["10", "6", "0.75", "1.125", "0.0075", "5·8·10·15", "—"], ["", "0", "1", "2", "3", "4"]]


# ---------------------------------------------------------------- 예약 작업
def test_the_jobs_list_has_the_shadow_timer(monkeypatch):
    assert "paperbot-paramshadow" in J.UNITS and J._UNIT.match("paperbot-paramshadow")
    kit = _read(SCREENS, "server-kit.js")
    assert re.search(r'\{unit: "paperbot-paramshadow", ko: "커스텀값 그림자", what: "[^"]+", cal: \{daily: \[1, 0\]\}\}', kit)
    assert "OnCalendar=*-*-* 01:00:00 UTC" in _read(ROOT, "deploy", "paperbot-paramshadow.timer")     # = 10:00 KST
    assert '"paperbot-paramshadow": "커스텀값 그림자"' in _read(V4, "core", "since.js")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        units = [c for c in cmd if c.startswith("paperbot-")]
        if units[0].endswith(".timer"):
            out = "\n\n".join(f"Id={u}\nLoadState=loaded\nUnitFileState=enabled\nActiveState=active\n"
                              f"LastTriggerUSec=Fri 2026-10-09 01:00:03 UTC\nNextElapseUSecRealtime=Sat 2026-10-10 01:00:00 UTC" for u in units)
        else:
            out = "\n\n".join(f"Id={u}\nLoadState=loaded\nActiveState=inactive\nSubState=dead\nResult=success\n"
                              f"ExecMainExitTimestamp=Fri 2026-10-09 01:04:00 UTC" for u in units)
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    d = J.jobs(run)
    row = d["jobs"]["paperbot-paramshadow"]
    assert d["available"] and row["state"] == "on" and row["ok"] is True
    assert row["last_ms"] == J.parse_ts("Fri 2026-10-09 01:00:03 UTC")
    assert row["next_ms"] == J.parse_ts("Sat 2026-10-10 01:00:00 UTC") and any("paperbot-paramshadow.timer" in c for c in calls)
