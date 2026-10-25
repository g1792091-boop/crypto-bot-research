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
    assert _oom("paperbot-executor-deepcoin.service") == -900   # the third executor (DeepCoin, owners 10-24)
    assert _oom("paperbot-executor-wooxpro2.service") == -900   # the fourth executor (WOO X Pro 2, owners 10-24)
    assert _oom("paperbot-combo.service") == -500
    assert _oom("paperbot-combo-mexc.service") == -500       # the -35 % paper bot MEXC follows (docs/live15-mexc-ko.md)
    assert _oom("paperbot-combo-vwap.service") == -500       # the 'VWAP 개선판' paper bot one executor follows (10-23)
    assert _oom("paperbot-combo-friend.service") == -500     # the '친구 매매법' paper bot WOO X Pro 2 follows (10-24)
    assert _oom("paperbot-combo-short5.service") == -500     # the '숏5 하락장' paper bot one executor follows (10-25)
    assert _oom("paperbot-live3.service") == -500


def test_experiments_are_not_protected():
    for unit in sorted(DEPLOY.glob("paperbot-*.service")):
        if unit.name in {"paperbot-executor.service", "paperbot-executor-mexc.service", "paperbot-executor-deepcoin.service",
                         "paperbot-executor-wooxpro2.service", "paperbot-mixchop.service",
                         "paperbot-combo.service", "paperbot-combo-mexc.service", "paperbot-combo-vwap.service",
                         "paperbot-combo-friend.service", "paperbot-combo-short5.service",
                         "paperbot-live3.service"}:
            continue
        v = _oom(unit.name)
        assert v is None or v >= 0, unit.name


def test_dashboard_reads_the_executor_records_but_never_the_keys():
    """Owners 10-19: the 실거래 screen showed 못 읽음 while paperbot-dash.service hid /var/lib/paperbot/exec. The
    folder is read-only there now; the key file stays hidden."""
    lines = (DEPLOY / "paperbot-dash.service").read_text(encoding="utf-8").splitlines()
    ro = next(x for x in lines if x.startswith("ReadOnlyPaths=")).split("=", 1)[1].split()
    hidden = next(x for x in lines if x.startswith("InaccessiblePaths=")).split("=", 1)[1].split()
    assert "-/var/lib/paperbot/exec" in ro and "-/var/lib/paperbot/exec" not in hidden
    assert "-/etc/paperbot/executor.env" in hidden
    assert not any(x.startswith("EnvironmentFile=/etc/paperbot/executor.env") for x in lines)
