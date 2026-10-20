"""deploy/combo_drop.py (owners 10/20 night: "레인지 필터만 매매법 빼줘"): one setting out of both paper bots' configs.

- without --write nothing changes (it says what would); with it only that members item goes, every other value stays,
  the file keeps its look (the member's own line removed) and its mode, the old file is kept beside it
- a file without it is left alone ("이미 없음"), a file with it twice is refused, a missing file is skipped
- the repo's own configs no longer have it (deploy/combo.live15.json, deploy/combo.live15-mexc.json)
"""
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("combo_drop", ROOT / "deploy" / "combo_drop.py")
CD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CD)
F7 = '  {"strategy": "F7_RF_ONLY", "tf": "1h", "no_chase": true},\n'


def _with_f7(src: Path, dst: Path) -> Path:
    """The repo config as the server had it on 10/20 (레인지 필터만 the 13th, before FVG 되돌림)."""
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    i = next(j for j, ln in enumerate(lines) if '"F9_FVG"' in ln)
    dst.write_text("".join(lines[:i] + [F7] + lines[i:]), encoding="utf-8")
    os.chmod(dst, 0o640)
    return dst


def test_the_repo_configs_no_longer_have_it():
    for f in ("combo.live15.json", "combo.live15-mexc.json"):
        d = json.loads((ROOT / "deploy" / f).read_text(encoding="utf-8"))
        assert len(d["members"]) == 14 and not any(m["strategy"] == "F7_RF_ONLY" for m in d["members"])
        assert [m["strategy"] for m in d["members"] if m.get("no_chase")] == ["F3_BOS", "F9_FVG", "N12_ICHI_AO"]


def test_shows_then_writes_only_that_member(tmp_path, capsys):
    a = _with_f7(ROOT / "deploy" / "combo.live15.json", tmp_path / "combo.json")
    b = _with_f7(ROOT / "deploy" / "combo.live15-mexc.json", tmp_path / "combo-mexc.json")
    before = {p: p.read_text(encoding="utf-8") for p in (a, b)}
    assert CD.main(["F7_RF_ONLY@1h", "--config", str(a), "--config", str(b)]) == 0
    out = capsys.readouterr().out
    assert "매매법 15개 -> 14개" in out and "추격 막기 4개 -> 3개" in out and "13. F9_FVG@1h (추격 막기)" in out and "--write" in out
    assert {p: p.read_text(encoding="utf-8") for p in (a, b)} == before               # shown only
    assert CD.main(["F7_RF_ONLY@1h", "--config", str(a), "--config", str(b), "--write"]) == 0
    out = capsys.readouterr().out
    assert "바꿈" in out and "systemctl restart paperbot-combo paperbot-combo-mexc" in out
    for p, src in ((a, "combo.live15.json"), (b, "combo.live15-mexc.json")):
        assert p.read_text(encoding="utf-8") == (ROOT / "deploy" / src).read_text(encoding="utf-8")   # the line, nothing else
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o640
        olds = list(tmp_path.glob(p.name + ".before-drop-*"))
        assert len(olds) == 1 and olds[0].read_text(encoding="utf-8") == before[p]
    # again: already gone, nothing changes
    assert CD.main(["F7_RF_ONLY@1h", "--config", str(a), "--write"]) == 0
    assert "이미 없음" in capsys.readouterr().out
    assert len(list(tmp_path.glob("combo.json.before-drop-*"))) == 1


def test_twice_refused_missing_skipped_and_another_shape_rewritten(tmp_path, capsys):
    two = tmp_path / "two.json"
    d = json.loads((ROOT / "deploy" / "combo.live15.json").read_text(encoding="utf-8"))
    d["members"] += [{"strategy": "F7_RF_ONLY", "tf": "1h"}, {"strategy": "F7_RF_ONLY", "tf": "1h", "no_chase": True}]
    two.write_text(json.dumps(d), encoding="utf-8")
    assert CD.main(["F7_RF_ONLY@1h", "--config", str(two), "--write"]) == 1
    assert "2번 있습니다" in capsys.readouterr().out and json.loads(two.read_text(encoding="utf-8")) == d
    assert CD.main(["F7_RF_ONLY@1h", "--config", str(tmp_path / "none.json")]) == 0
    assert "파일 없음" in capsys.readouterr().out
    one_line = tmp_path / "one.json"                                   # all on one line: written again as JSON
    d["members"] = d["members"][:-1]
    one_line.write_text(json.dumps(d), encoding="utf-8")
    assert CD.main(["F7_RF_ONLY@1h", "--config", str(one_line), "--write"]) == 0
    got = json.loads(one_line.read_text(encoding="utf-8"))
    assert got == {**d, "members": d["members"][:-1]}
    with pytest.raises(SystemExit):
        CD.main(["F7_RF_ONLY"])
