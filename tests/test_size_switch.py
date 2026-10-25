"""deploy/size_switch.py (owners 10-25 night: "b로해줘", always 40 % of the balance): a stopped live executor's config gets
``size_from: "equity"`` and ``margin_frac``; every other value stays; back to the newest copy."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from paperbot.executor import ExecConfig

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("size_switch", ROOT / "deploy" / "size_switch.py")
SS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SS)


def _exec(tmp_path, name):
    p = tmp_path / "executor.json"
    shutil.copyfile(ROOT / "deploy" / name, p)
    return str(p)


def test_dry_run_writes_nothing(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-bybit.json")
    before = Path(cfg).read_text()
    assert SS.main(["--exec", "bybit", "--config", cfg], active=lambda u: False) == 0
    out = capsys.readouterr().out
    assert Path(cfg).read_text() == before and not list(tmp_path.glob("*.before-size-*"))
    assert "size_from" in out and "margin_frac" in out and "보여 주기만" in out


@pytest.mark.parametrize("ex,name", [("bybit", "executor.live-bybit.json"), ("wooxpro", "executor.live-wooxpro.json"),
                                     ("bybit", "executor.live-bybit-vwap.json")])
def test_write_sets_equity_sizing_and_keeps_everything_else(tmp_path, ex, name):
    cfg = _exec(tmp_path, name)
    os.chmod(cfg, 0o640)
    old = json.loads(Path(cfg).read_text())
    assert SS.main(["--exec", ex, "--config", cfg, "--write"], active=lambda u: False) == 0
    new = json.loads(Path(cfg).read_text())
    assert (new["size_from"], new["margin_frac"]) == ("equity", 0.4)
    assert {k: v for k, v in new.items() if k not in ("size_from", "margin_frac")} == old
    assert oct(os.stat(cfg).st_mode & 0o777) == oct(0o640)
    c = ExecConfig.from_dict(new)
    assert c.problems() == [] and (c.size_from, c.margin_frac) == ("equity", 0.4)
    backups = list(tmp_path.glob("executor.json.before-size-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == old
    assert SS.main(["--exec", ex, "--back", "--config", cfg, "--write"], active=lambda u: False) == 0
    assert json.loads(Path(cfg).read_text()) == old


def test_deepcoin_template_already_has_it(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-deepcoin.json")
    before = json.loads(Path(cfg).read_text())
    assert SS.main(["--exec", "deepcoin", "--config", cfg, "--write"], active=lambda u: False) == 0
    assert json.loads(Path(cfg).read_text()) == before          # nothing to change


def test_refusals(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-bybit.json")
    before = Path(cfg).read_text()
    assert SS.main(["--exec", "bybit", "--config", cfg, "--write"], active=lambda u: True) == 1
    assert "paperbot-executor" in capsys.readouterr().out
    assert SS.main(["--exec", "wooxpro", "--config", cfg, "--write"], active=lambda u: False) == 1
    assert "거래소는 'bybit'" in capsys.readouterr().out
    assert SS.main(["--exec", "bybit", "--margin", "1.5", "--config", cfg, "--write"], active=lambda u: False) == 1
    assert SS.main(["--exec", "bybit", "--back", "--config", cfg], active=lambda u: False) == 1
    assert Path(cfg).read_text() == before
