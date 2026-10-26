"""deploy/trend_drop.py (owners 10-26: "추세판단봇 … 피보나치 매매법들 다 빼주라"): only the F16_FIB members leave the server's
/etc/paperbot/combo.json; every other value, the design name and the file's owner and mode stay; the old copy is kept;
nothing is written without --write; a second run finds nothing; a config that is not the trend bot's, or one that would
keep no member, is refused; another layout of the file is written again as JSON with the same values."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deploy import trend_drop as D  # noqa: E402
from paperbot import combo as C  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIB = ["F16_FIB382@30m", "F16_FIB382@1h", "F16_FIB500@1h", "F16_FIB618@4h", "F16_FIB764@4h"]


def _server_file(tmp_path):
    """The server's combo.json as it was before 10-26: the repository's 10-22 trend config with the five Fibonacci members
    back in their places (the repository's own file no longer has them)."""
    with open(os.path.join(ROOT, "deploy", "combo.trend.json"), encoding="utf-8") as fh:
        lines = fh.read().splitlines(keepends=True)
    at = {'"N05_PSAR_POC", "tf": "30m"': ['F16_FIB382", "tf": "30m'],
          '"F9_IFVG", "tf": "1h"': ['F16_FIB382", "tf": "1h', 'F16_FIB500", "tf": "1h'],
          '"F10_OTE", "tf": "4h"': ['F16_FIB618", "tf": "4h', 'F16_FIB764", "tf": "4h']}
    out = []
    for ln in lines:
        out.append(ln)
        for key, adds in at.items():
            if key in ln:
                out += ['  {"strategy": "' + a + '", "no_chase": true},\n' for a in adds]
    p = tmp_path / "combo.json"
    p.write_text("".join(out), encoding="utf-8")
    os.chmod(p, 0o640)
    return p


def _labels(cfg: dict) -> list:
    return [f"{m['strategy']}@{m['tf']}" for m in cfg["members"]]


def test_shows_then_drops_only_the_fibonacci_members(tmp_path, capsys):
    p = _server_file(tmp_path)
    before = p.read_text(encoding="utf-8")
    old = json.loads(before)
    assert len(old["members"]) == 18 and set(FIB) <= set(_labels(old))
    assert D.main(["--combo", str(p)]) == 0
    out = capsys.readouterr().out
    assert "진입 매매법 18개 → 13개" in out and "보여 주기만" in out
    assert ("빼는 것: 피보나치 38.2% 30분 · 피보나치 38.2% 1시간 · 피보나치 50% 1시간 · 피보나치 61.8% 4시간 · "
            "피보나치 76.4% 4시간") in out and "설계 이름 2026-10-22 그대로라 성적은 이어서 셈" in out
    assert p.read_text(encoding="utf-8") == before                                       # nothing written
    assert D.main(["--combo", str(p), "--write"]) == 0
    out = capsys.readouterr().out
    backups = [f for f in os.listdir(tmp_path) if f.startswith("combo.json.before-drop-")]
    assert len(backups) == 1 and (tmp_path / backups[0]).read_text(encoding="utf-8") == before
    new = json.loads(p.read_text(encoding="utf-8"))
    assert _labels(new) == [x for x in _labels(old) if x not in FIB] and len(new["members"]) == 13
    assert {k: v for k, v in new.items() if k != "members"} == {k: v for k, v in old.items() if k != "members"}
    assert new["trend"]["design"] == "2026-10-22"
    # line by line: only the five member lines left the file
    gone = [ln for ln in before.splitlines() if ln not in p.read_text(encoding="utf-8").splitlines()]
    assert len(gone) == 5 and all("F16_FIB" in ln for ln in gone)
    assert oct(os.stat(p).st_mode & 0o777) == "0o640"
    # the same as the repository's own file now, and the bot's own checker takes it
    with open(os.path.join(ROOT, "deploy", "combo.trend.json"), encoding="utf-8") as fh:
        assert new == json.load(fh)
    cfg = C.ComboConfig.from_file(str(p))
    assert cfg.problems() == []
    assert D.main(["--combo", str(p)]) == 0 and "이미 빠져 있어요" in capsys.readouterr().out


def test_refusals_and_another_layout(tmp_path, capsys):
    p = tmp_path / "combo.json"
    p.write_text(json.dumps({"db": "x.db", "members": [{"strategy": "F16_FIB382", "tf": "1h"}]}), encoding="utf-8")
    assert D.main(["--combo", str(p), "--write"]) == 1 and "추세판단 봇 설정이 아니에요" in capsys.readouterr().out
    p.write_text(json.dumps({"trend": {"design": "x"}, "members": [{"strategy": "F16_FIB382", "tf": "1h"}]}), encoding="utf-8")
    assert D.main(["--combo", str(p), "--write"]) == 1 and "하나도 남지 않아요" in capsys.readouterr().out
    assert D.main(["--combo", str(tmp_path / "none.json")]) == 1 and "멈춤" in capsys.readouterr().out
    # one line for the whole file: written again as JSON, the same values without the dropped members
    cfg = {"trend": {"design": "2026-10-22"}, "db": "x.db", "members": [{"strategy": "V39_ALL", "tf": "1h"},
                                                                       {"strategy": "F16_FIB500", "tf": "1h"}], "margin": 0.4}
    p.write_text(json.dumps(cfg), encoding="utf-8")
    assert D.main(["--combo", str(p), "--write"]) == 0
    assert json.loads(p.read_text(encoding="utf-8")) == {**cfg, "members": [{"strategy": "V39_ALL", "tf": "1h"}]}
    # another prefix when asked
    p.write_text(json.dumps({**cfg, "members": cfg["members"] + [{"strategy": "F10_OTE", "tf": "4h"}]}), encoding="utf-8")
    assert D.main(["--combo", str(p), "--write", "--drop", "F10_OTE"]) == 0
    assert [m["strategy"] for m in json.loads(p.read_text(encoding="utf-8"))["members"]] == ["V39_ALL", "F16_FIB500"]
