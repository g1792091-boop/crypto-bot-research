"""Right after a reset (deploy/paperbot-reset.sh) a Persistent timer can catch up before the bot has created
paper3.db (review m2): the jobs that read it exit 0 with an INFO line instead of failing (a failure would send a
"작업 실패" Telegram through paperbot-failed@). Nothing is created and nothing is fetched."""

import os

from paperbot import checkpoint as ck
from paperbot import checkpoint_preview as cp
from paperbot import daily3 as d3


def _no_network(monkeypatch):
    import paperbot.live as live
    monkeypatch.setattr(live, "_rest", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no REST call")))
    monkeypatch.setattr(live, "_notifier", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no notifier")))


def test_checkpoint_skips_without_paper3(tmp_path, monkeypatch, capsys):
    _no_network(monkeypatch)
    out = tmp_path / "checkpoint.db"
    assert ck.main(["run", "--db", str(tmp_path / "paper3.db"), "--out", str(out)]) == 0
    assert "nothing to judge, skipped" in capsys.readouterr().out
    assert not out.exists() and not (tmp_path / "paper3.db").exists()


def test_daily3_skips_without_paper3(tmp_path, monkeypatch, capsys):
    _no_network(monkeypatch)
    out = tmp_path / "daily3.db"
    assert d3.main(["run", "--db", str(tmp_path / "paper3.db"), "--out", str(out)]) == 0
    assert "nothing to check, skipped" in capsys.readouterr().out
    assert not out.exists() and not (tmp_path / "paper3.db").exists()


def test_rehearsal_skips_without_paper3(tmp_path, monkeypatch, capsys):
    _no_network(monkeypatch)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    reh = tmp_path / "rehearsal"
    assert cp.main(["--db", str(tmp_path / "paper3.db"), "--rehearsal-dir", str(reh)]) == 0
    assert "nothing to rehearse, skipped" in capsys.readouterr().out
    assert not reh.exists() and not (tmp_path / "paper3.db").exists()
