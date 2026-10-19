"""Owners 2026-10-19: the real-money chain (rule bot 1m bars -> live paper bot -> two executors) shares the server
with the experiments, so in a server-wide memory shortage the kernel must kill experiments first."""
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def _oom(unit: str):
    for line in (DEPLOY / unit).read_text(encoding="utf-8").splitlines():
        if line.startswith("OOMScoreAdjust="):
            return int(line.split("=", 1)[1])
    return None


def test_live_chain_is_protected_from_the_oom_killer():
    assert _oom("paperbot-executor.service") == -900
    assert _oom("paperbot-executor-mexc.service") == -900
    assert _oom("paperbot-combo.service") == -500
    assert _oom("paperbot-live3.service") == -500


def test_experiments_are_not_protected():
    for unit in sorted(DEPLOY.glob("paperbot-*.service")):
        if unit.name in {"paperbot-executor.service", "paperbot-executor-mexc.service", "paperbot-combo.service",
                         "paperbot-live3.service"}:
            continue
        v = _oom(unit.name)
        assert v is None or v >= 0, unit.name
