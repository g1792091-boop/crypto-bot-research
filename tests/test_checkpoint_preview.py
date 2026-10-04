"""Checkpoint rehearsal (paperbot/checkpoint_preview.py): the real verdict path on a new file, never the real
checkpoint.db or Telegram."""

import hashlib
import os
import time

import pytest

from paperbot import checkpoint as ck
from paperbot import checkpoint_preview as pv
from test_checkpoint import BR, DAY, SPECS, _paper_db, _trades, synth_minutes


class _Rest:
    def exchange_info(self, symbols):
        return SPECS


class _Minutes:
    """Stands in for BinanceMinutes (synthetic 1m bars, no network)."""

    def __init__(self, rest, cache):
        self.cache, self.fetched_days = cache, 0

    def load(self, lo, hi):
        return synth_minutes(lo, hi, seed=2)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A run that started 8 days before today with the runner's state of today 00:00 UTC; the real
    checkpoint.db path points into tmp_path."""
    import paperbot.live as live
    monkeypatch.setattr(os, "geteuid", lambda: 1000)              # the tests may run as root; the tool refuses it
    monkeypatch.setattr(live, "_notifier", lambda: pytest.fail("the rehearsal built a notifier"))
    monkeypatch.setattr(live, "_rest", _Rest)
    monkeypatch.setattr(live, "load_brackets", lambda *a: (BR, "test"))
    monkeypatch.setattr(ck, "BinanceMinutes", _Minutes)
    monkeypatch.setattr(pv, "REAL_OUT", str(tmp_path / "lib" / "checkpoint.db"))
    today = ck.floor_day(int(time.time() * 1000))
    lo = today - 8 * DAY + 5 * 3_600_000
    path = str(tmp_path / "paper3.db")
    _paper_db(path, {"GOOD@1h": {"wallet": 400_000.0, "trades": _trades(12, lo, today, 32_900.0), "signals": 100,
                                 "created": lo},
                     "FEW@1h": {"wallet": 5_100.0, "trades": _trades(5, lo, today, 20.0), "signals": 60,
                                "created": lo}}, today)
    return path, today


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_rehearsal_runs_the_verdict_path_on_a_new_file(world, tmp_path, capsys):
    path, today = world
    before = _sha(path)
    out = str(tmp_path / "preview.db")
    assert pv.main(["--db", path, "--out", out, "--bots", "100", "--as-of", ck.day_str(today)]) == 0
    v = ck.verdict(out, ck.day_str(today))
    assert v["day"] == 8                                       # today judged as if it were the checkpoint
    assert v["accounts"]["GOOD@1h"]["status"] == ck.PASS1    # 12 trades >= --min-trades 10
    assert v["accounts"]["FEW@1h"]["status"] == ck.HOLD
    assert (ck.PERIOD_DAYS, ck.MIN_TRADES) == (30, 30)        # changed only while it ran
    assert _sha(path) == before and not os.path.exists(pv.REAL_OUT)
    assert "미리보기 끝" in capsys.readouterr().out


def test_rehearsal_refuses_an_existing_or_the_real_out(world, tmp_path, monkeypatch):
    import paperbot.live as live
    path, _ = world
    monkeypatch.setattr(live, "_rest", lambda: pytest.fail("Binance called after a refusal"))
    old = tmp_path / "old.db"
    old.write_bytes(b"a verdict file")
    assert pv.main(["--db", path, "--out", str(old)]) == 2
    assert old.read_bytes() == b"a verdict file"
    os.makedirs(os.path.dirname(pv.REAL_OUT))
    assert pv.main(["--db", path, "--out", pv.REAL_OUT]) == 2           # even before the real one exists
    assert not os.path.exists(pv.REAL_OUT)
    os.symlink(pv.REAL_OUT, str(tmp_path / "link.db"))
    assert pv.main(["--db", path, "--out", str(tmp_path / "link.db")]) == 2
    assert not os.path.exists(pv.REAL_OUT)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert pv.main(["--db", path, "--out", str(tmp_path / "new.db")]) == 2      # root: the cache must stay the job's
    assert not os.path.exists(tmp_path / "new.db")


def test_documented_command_runs_as_paperbot_and_leaves_no_failed_unit():
    """docs/server-setup-v3.md: a rehearsal that exits non-zero must not stay in `systemctl --failed`, which the
    owners' guide treats as a job failure (--collect unloads the transient unit even when it failed)."""
    doc = os.path.join(os.path.dirname(__file__), "..", "docs", "server-setup-v3.md")
    cmd = [ln for ln in open(doc, encoding="utf-8") if "-m paperbot.checkpoint_preview" in ln]
    assert len(cmd) == 1
    assert "sudo systemd-run --wait --pipe --collect -p User=paperbot " in cmd[0]


def test_weekly_rehearsal_writes_a_fresh_file_a_summary_and_keeps_the_last_four(world, tmp_path, monkeypatch):
    """--rehearsal-dir (deploy/paperbot-rehearsal.service): a new rehearsal-<time>.db, its JSON summary and
    latest.json; older rehearsals beyond --keep are removed; the real checkpoint.db is never written."""
    import json
    path, today = world
    folder = tmp_path / "rehearsal"
    folder.mkdir()
    for k in range(5):                                             # five older rehearsals (and a -wal of one)
        stem = folder / f"rehearsal-2026090{k + 1}T033000Z"
        (folder / (stem.name + ".db")).write_bytes(b"x")
        (folder / (stem.name + ".json")).write_text("{}")
    (folder / "rehearsal-20260901T033000Z.db-wal").write_bytes(b"x")
    (folder / "notes.txt").write_text("not ours")
    (folder / "bars").mkdir()
    before = _sha(path)
    assert pv.main(["--db", path, "--rehearsal-dir", str(folder), "--bots", "100", "--as-of",
                    ck.day_str(today), "--cache", str(folder / "bars")]) == 0
    dbs = sorted(p.name for p in folder.glob("rehearsal-*.db"))
    assert len(dbs) == 4 and dbs[:3] == [f"rehearsal-2026090{k}T033000Z.db" for k in (3, 4, 5)]
    assert not (folder / "rehearsal-20260901T033000Z.db-wal").exists()
    assert (folder / "notes.txt").exists() and (folder / "bars").is_dir()
    assert sorted(p.name for p in folder.glob("rehearsal-*.json")) == [d[:-3] + ".json" for d in dbs]
    s = json.loads((folder / (dbs[-1][:-3] + ".json")).read_text())
    assert s == json.loads((folder / "latest.json").read_text()) == pv.latest_summary(str(folder))
    assert s["status"] == "ok" and s["as_of"] == ck.day_str(today) and s["days"] == 8
    assert s["accounts_in_snapshot"] == 2 and s["counts"][ck.PASS1] == 1 and s["counts"][ck.HOLD] == 1
    assert s["zero_rate_accounts"] == [] and s["rate_min"] > 0 and isinstance(s["warnings"], list)
    assert s["runtime_s"] >= 0 and s["out"].endswith(dbs[-1]) and s["bots"] == 100 and s["min_trades"] == 10
    assert ck.verdict(s["out"], ck.day_str(today))["day"] == 8
    assert _sha(path) == before and not os.path.exists(pv.REAL_OUT)


def test_a_failed_rehearsal_still_writes_its_summary_and_exits_non_zero(world, tmp_path, monkeypatch):
    import json

    import paperbot.live as live
    path, today = world

    def down():
        raise ConnectionError("binance down")
    monkeypatch.setattr(live, "_rest", down)
    folder = tmp_path / "rehearsal"
    assert pv.main(["--db", path, "--rehearsal-dir", str(folder), "--as-of", ck.day_str(today)]) == 1
    s = json.loads((folder / "latest.json").read_text())
    assert s["status"] == "failed" and "binance down" in s["error"] and s["as_of"] == ck.day_str(today)
    assert "accounts_in_snapshot" not in s
    assert not os.path.exists(pv.REAL_OUT)


def test_rehearsal_dir_refusals(world, tmp_path, monkeypatch):
    import paperbot.live as live
    path, _ = world
    monkeypatch.setattr(live, "_rest", lambda: pytest.fail("Binance called after a refusal"))
    assert pv.main(["--db", path]) == 2                                          # neither --out nor a folder
    assert pv.main(["--db", path, "--out", str(tmp_path / "a.db"), "--rehearsal-dir", str(tmp_path)]) == 2
    os.makedirs(os.path.dirname(pv.REAL_OUT))
    assert pv.main(["--db", path, "--rehearsal-dir", os.path.dirname(pv.REAL_OUT)]) == 2   # the verdict folder
    assert pv.main(["--db", path, "--rehearsal-dir", str(tmp_path / "r"), "--keep", "0"]) == 2
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert pv.main(["--db", path, "--rehearsal-dir", str(tmp_path / "root")]) == 2
    assert not (tmp_path / "root").exists()


def test_summary_of_counts_zero_rate_accounts():
    v = {"accounts": {"A@1h": {"rate": 0.0}, "B@1h": {"rate": 0.01}, "C@4h": {}}, "tested": 1,
         "warnings": ["w"], "counts": {"PASS1": 1}, "runtime_s": 3.0, "snapshot_sha256": "ab"}
    s = pv.summary_of(v, as_of="2026-10-07", days=6, out="/x.db", started=0.0, finished=2.5, status="ok")
    assert s["zero_rate_accounts"] == ["A@1h"] and (s["rate_min"], s["rate_max"]) == (0.0, 0.01)
    assert s["accounts_in_snapshot"] == 3 and s["runtime_s"] == 2.5 and s["started_utc"] == "1970-01-01T00:00:00Z"
    assert s["warnings"] == ["w"] and s["counts"] == {"PASS1": 1} and s["tested"] == 1
