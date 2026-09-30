"""차트 패턴 자동 인식(JS) — 모양이 분명한 가격 경로에서 패턴과 돌파 방향을 맞게 찾는지. node 가 없으면 건너뜀."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "ind.js"


def _path(vertices, t0=1_700_000_000):
    """꼭짓점 (봉 번호, 가격) 을 직선으로 이은 캔들."""
    closes = []
    for (i0, p0), (i1, p1) in zip(vertices, vertices[1:]):
        for i in range(i0, i1):
            closes.append(p0 + (p1 - p0) * (i - i0) / (i1 - i0))
    closes.append(vertices[-1][1])
    out, prev = [], closes[0]
    for k, cl in enumerate(closes):
        out.append({"time": t0 + k * 3600, "open": prev, "high": max(prev, cl) + 0.2, "low": min(prev, cl) - 0.2, "close": cl, "volume": 100.0})
        prev = cl
    return out


def _run(tmp_path, candles, params):
    shutil.copy(JS, tmp_path / "ind.mjs")
    (tmp_path / "c.json").write_text(json.dumps(candles))
    (tmp_path / "run.mjs").write_text(f"""
import fs from "fs";
import {{ detectPatterns, INDICATORS }} from "./ind.mjs";
const c = JSON.parse(fs.readFileSync(process.argv[2]));
const r = INDICATORS.chartpat.compute(c, {{ ...INDICATORS.chartpat.params, ...{json.dumps(params)} }});
console.log(JSON.stringify({{ pats: detectPatterns(c, {json.dumps(params)}), note: r.note, n: r.plots[0].data.length }}));
""")
    return json.loads(subprocess.check_output(["node", str(tmp_path / "run.mjs"), str(tmp_path / "c.json")], text=True))


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_double_bottom_breaks_up(tmp_path):
    c = _path([(0, 135), (5, 140), (25, 100), (40, 112), (55, 100.2), (75, 125)])
    r = _run(tmp_path, c, {"len": 3})
    assert r["n"] == len(c)
    db = [p for p in r["pats"] if p["key"] == "db"]
    assert db and db[-1]["st"] == "up" and db[-1]["ok"]
    assert abs(db[-1]["target"] - (112 + 12)) < 2          # 넥라인 + 깊이 (측정 이동)
    assert db[-1]["reached"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_double_top_mirror_breaks_down(tmp_path):
    c = _path([(0, 65), (5, 60), (25, 100), (40, 88), (55, 99.8), (75, 75)])
    r = _run(tmp_path, c, {"len": 3})
    dt = [p for p in r["pats"] if p["key"] == "dt"]
    assert dt and dt[-1]["st"] == "down" and dt[-1]["ok"] and dt[-1]["target"] < 88


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_ascending_triangle_and_forming_state(tmp_path):
    verts = [(0, 102), (5, 100), (15, 120), (25, 107), (35, 120.2), (45, 113), (52, 120.1)]
    done = _run(tmp_path, _path(verts + [(62, 132)]), {"len": 3})
    asc = [p for p in done["pats"] if p["key"] == "asc"]
    assert asc and asc[-1]["st"] == "up" and asc[-1]["name"] == "상승 삼각형"
    # 돌파 전(삼각형 안에서 끝남) → 형성 중 + 위쪽 목표
    live = _run(tmp_path, _path(verts + [(57, 117)]), {"len": 3})
    asc = [p for p in live["pats"] if p["key"] == "asc"]
    assert asc and asc[-1]["st"] == "forming" and asc[-1]["target"] > 120
    assert "상승 삼각형" in live["note"]
