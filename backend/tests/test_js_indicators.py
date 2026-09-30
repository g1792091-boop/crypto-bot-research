"""화면(JS)과 백테스트(Python)의 보조지표 수치가 같은지 확인. node 가 없으면 건너뜀."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import indicators as ind
from app.data import synthetic

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "ind.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_js_indicators_match_python(tmp_path):
    c = synthetic.candles("BTCUSDT", "1h", 400, seed=5)
    cl = [b["close"] for b in c]
    expect = {"ema": ind.ema(cl, 20), "rsi": ind.rsi(cl, 14), "atr": ind.atr(c, 14), "macd": ind.macd(cl)["hist"],
              "adx": ind.adx(c)["adx"], "stoch": ind.stoch(c)["k"], "bbu": ind.bbands(cl)["upper"], "cci": ind.cci(c, 20),
              "st": ind.supertrend(c, 10, 3)["trend"]}
    shutil.copy(JS, tmp_path / "ind.mjs")
    (tmp_path / "data.json").write_text(json.dumps(c))
    (tmp_path / "run.mjs").write_text("""
import fs from "fs";
import { INDICATORS as I, ema, rsi, atr } from "./ind.mjs";
const c = JSON.parse(fs.readFileSync(process.argv[2])), cl = c.map((b) => b.close);
const st = I.supertrend.compute(c, { length: 10, mult: 3 }).plots;
const out = { ema: ema(cl, 20), rsi: rsi(cl, 14), atr: atr(c, 14),
  macd: I.macd.compute(c, { fast: 12, slow: 26, signal: 9 }).plots[0].data, adx: I.adx.compute(c, { length: 14 }).plots[0].data,
  stoch: I.stoch.compute(c, { length: 14, k: 3, d: 3 }).plots[0].data, bbu: I.bb.compute(c, { length: 20, mult: 2 }).plots[0].data,
  cci: I.cci.compute(c, { length: 20 }).plots[0].data, st: st[0].data.map((v, i) => v != null ? 1 : st[1].data[i] != null ? -1 : null) };
let bad = [];
for (const [k, d] of Object.entries(I)) { try { d.compute(c, d.params, {}).plots.forEach((p) => p.data.length !== c.length && bad.push(k)); } catch (e) { bad.push(k + ":" + e.message); } }
out.bad = bad;
console.log(JSON.stringify(out));
""")
    got = json.loads(subprocess.check_output(["node", str(tmp_path / "run.mjs"), str(tmp_path / "data.json")], text=True))
    assert got.pop("bad") == []
    for k, exp in expect.items():
        for a, b in zip(got[k], exp):
            assert (a is None) == (b is None), k
            if a is not None:
                assert abs(a - b) <= 1e-9 * max(1.0, abs(b)), k
