"""deploy/vwap_switch.py: one live executor moved to the 'VWAP 개선판' paper bot (owners 10-23), only while it is stopped
and the VWAP paper bot has an account; every other value of its config stays; back to the newest copy."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from paperbot.executor import ExecConfig
from paperbot.store3 import Store3

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vwap_switch", ROOT / "deploy" / "vwap_switch.py")
VS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VS)


def _paper(tmp_path, wallet=1234.5):
    db = str(tmp_path / "vwap.db")
    s = Store3(db)
    s.put_state("accounts", 1, {"engines": {"COMBO@mix": {"wallet": wallet, "position": None}}})
    s.commit()
    s.conn.close()
    return db


def _exec(tmp_path, name):
    p = tmp_path / "executor.json"
    shutil.copyfile(ROOT / "deploy" / name, p)
    return str(p)


def test_dry_run_writes_nothing_and_lists_the_changes(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-bybit.json")
    before = Path(cfg).read_text()
    rc = VS.main(["--exec", "bybit", "--balance", "150", "--config", cfg], active=lambda u: False,
                 wallet_of=lambda: 1000.0)
    out = capsys.readouterr().out
    assert rc == 0 and Path(cfg).read_text() == before and not list(tmp_path.glob("*.before-vwap-*"))
    for k in ("paper_db", "ladder", "signal_light_n", "budget_usd", "qty_scale", "risk.max_loss_frac"):
        assert k in out
    assert "보여 주기만" in out


@pytest.mark.parametrize("ex,name", [("bybit", "executor.live-bybit.json"), ("wooxpro", "executor.live-wooxpro.json")])
def test_write_moves_the_executor_and_keeps_everything_else(tmp_path, ex, name):
    cfg = _exec(tmp_path, name)
    os.chmod(cfg, 0o640)
    old = json.loads(Path(cfg).read_text())
    db = _paper(tmp_path, wallet=1250.0)
    rc = VS.main(["--exec", ex, "--balance", "125", "--config", cfg, "--write"], active=lambda u: False,
                 wallet_of=lambda: VS.paper_wallet(db))
    assert rc == 0
    new = json.loads(Path(cfg).read_text())
    assert new["paper_db"] == "/var/lib/paperbot/combo/vwap.db"
    assert new["ladder"] == {"first_lock": 0.08, "trigger_gap": 0.02, "step": 0.04}     # owners 10-27: 10 -> 8, every 4
    assert new["signal_light_n"] == 20 and new["signal_light_min_win"] == 0.75
    assert new["risk"]["max_loss_frac"] == 0.2 and new["budget_usd"] == 125 and new["qty_scale"] == 0.1
    assert (new["leverage_by_symbol"], new["liq_guard"], new["liq_guard_mmr"]) == ({"BTCUSDT": 40, "*": 30}, True, 0.005)
    for k in set(old) - {"paper_db", "ladder", "signal_light_n", "signal_light_min_win", "budget_usd", "qty_scale",
                         "risk", "leverage_by_symbol", "liq_guard", "liq_guard_mmr"}:
        assert new[k] == old[k], k
    assert {k: v for k, v in new["risk"].items() if k != "max_loss_frac"} == \
        {k: v for k, v in old["risk"].items() if k != "max_loss_frac"}
    assert oct(os.stat(cfg).st_mode & 0o777) == oct(0o640)
    assert ExecConfig.from_dict(new).problems() == []
    backups = list(tmp_path.glob("executor.json.before-vwap-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == old
    # and back
    assert VS.main(["--exec", ex, "--back", "--config", cfg, "--write"], active=lambda u: False) == 0
    assert json.loads(Path(cfg).read_text()) == old


def test_refusals(tmp_path, capsys):
    cfg = _exec(tmp_path, "executor.live-bybit.json")
    before = Path(cfg).read_text()
    # the executor runs: nothing written
    assert VS.main(["--exec", "bybit", "--balance", "100", "--config", cfg, "--write"], active=lambda u: True,
                   wallet_of=lambda: 1000.0) == 1
    assert "paperbot-executor" in capsys.readouterr().out
    # the other exchange's file
    assert VS.main(["--exec", "wooxpro", "--balance", "100", "--config", cfg, "--write"], active=lambda u: False,
                   wallet_of=lambda: 1000.0) == 1
    assert "거래소는 'bybit'" in capsys.readouterr().out
    # no paper bot record yet
    assert VS.main(["--exec", "bybit", "--balance", "100", "--config", cfg, "--write"], active=lambda u: False,
                   wallet_of=lambda: VS.paper_wallet(str(tmp_path / "missing.db"))) == 1
    assert "paperbot-combo-vwap" in capsys.readouterr().out
    # no balance
    assert VS.main(["--exec", "bybit", "--config", cfg], active=lambda u: False, wallet_of=lambda: 1000.0) == 1
    # nothing to go back to
    assert VS.main(["--exec", "bybit", "--back", "--config", cfg], active=lambda u: False) == 1
    assert Path(cfg).read_text() == before


def test_the_repository_templates_are_what_the_switch_writes(tmp_path):
    for ex, base, vw in (("bybit", "executor.live-bybit.json", "executor.live-bybit-vwap.json"),
                         ("wooxpro", "executor.live-wooxpro.json", "executor.live-wooxpro-vwap.json")):
        cur = (ROOT / "deploy" / base).read_text()
        new, _w = VS.plan_exec(cur, ex, 100.0, 1000.0)
        assert json.loads(new) == json.loads((ROOT / "deploy" / vw).read_text())
