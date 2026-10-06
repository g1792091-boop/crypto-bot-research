"""The shadow league inside the agents tick: OFF by default and then it changes nothing at all (no file, no query, not even
an import); ON it makes one league tick within a wall-time cap; the settings, the env template and the docs; and the
proof that no frozen file (the 331 accounts' code, the research folder, the locks) was touched or imports the new code."""

import fnmatch
import hashlib
import os
import posixpath
import subprocess
import sys

import pytest

from shadowleague_world import FakeExchange, make_member
from test_rooms import HOUR, QUIET, QueueRunner, World
from paperbot import runinfo as RI
from paperbot.agents import rooms as RM
from paperbot.shadowleague import hook as HK
from paperbot.shadowleague import league as LG
from paperbot.shadowleague import store as ST

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "10acaf638c7645f5ab4cd02931c70da14c8c0297"        # agents-next when the shadow league branch was cut


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def tick(world, policy, get=None, now=QUIET):
    return RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], QueueRunner({}),
                   policy=policy, now_ms=now, clock_ms=lambda: now, price_get=get)


def block_import(monkeypatch):
    """Make 'from ..shadowleague import hook' fail: the import of the hook is the first thing an ON tick does."""
    import paperbot.shadowleague as pkg
    monkeypatch.setitem(sys.modules, "paperbot.shadowleague.hook", None)
    monkeypatch.delattr(pkg, "hook", raising=False)


def league_files(world):
    d = os.path.dirname(world.paths["agents"])
    return sorted(f for f in os.listdir(d) if f.startswith("shadow_league"))


def league_exchange(now=QUIET, hours=1500):
    """A klines endpoint whose grid ends 'now - 1500 hours' ago, and the one-coin member that follows it."""
    t0 = ((now - hours * HOUR) // (4 * HOUR)) * (4 * HOUR)
    return FakeExchange(coins=("BTC",), tfs=("1h",), now_ms=now, t0=t0), make_member(start_ms=t0 + 1000 * HOUR, k=5), t0


# ------------------------------------------------------------------------------------------------ the switch
def test_the_switch_is_off_by_default_everywhere():
    assert RM.RoomsPolicy().shadow_league is False
    assert RM.policy_from_env({}).shadow_league is False
    assert RM.policy_from_env({"AGENTS_SHADOW_LEAGUE": ""}).shadow_league is False
    assert RM.policy_from_env({"AGENTS_SHADOW_LEAGUE": "0"}).shadow_league is False
    assert RM.policy_from_env({"AGENTS_SHADOW_LEAGUE": "1"}).shadow_league is True
    assert "AGENTS_SHADOW_LEAGUE" in RM.ENV_INTS and "AGENTS_SHADOW_LEAGUE" in RM.ENV_SWITCHES
    for bad in ("2", "yes", "-1", "on", "1.0"):
        with pytest.raises(ValueError):
            RM.policy_from_env({"AGENTS_SHADOW_LEAGUE": bad})
    assert HK.enabled(RM.RoomsPolicy(shadow_league=True)) and not HK.enabled(RM.RoomsPolicy())


def test_off_changes_nothing_no_file_no_query_not_even_an_import(world, monkeypatch, capsys):
    ex, member, t0 = league_exchange()
    block_import(monkeypatch)                                                       # an import of the hook would fail
    monkeypatch.setattr(ST.Store, "__init__", lambda *a, **k: (_ for _ in ()).throw(AssertionError("league database opened")))
    monkeypatch.setattr(LG.League, "tick", lambda *a, **k: (_ for _ in ()).throw(AssertionError("league ticked")))
    before = world.q("SELECT COUNT(*) FROM messages")
    out = tick(world, RM.RoomsPolicy(), ex.get)
    assert out["skipped"] == "" and out["rounds"] == []
    assert league_files(world) == []
    assert ex.requests == []                                                        # not one public request
    assert "shadow league" not in capsys.readouterr().err
    assert world.q("SELECT COUNT(*) FROM messages") == before


def test_on_one_league_tick_runs_inside_the_agents_tick_and_writes_only_its_own_database(world, monkeypatch):
    ex, member, t0 = league_exchange()
    monkeypatch.setattr(HK, "MEMBERS", (member,))
    paper_before = open(world.paths["paper"], "rb").read()
    out = tick(world, RM.RoomsPolicy(shadow_league=True), ex.get)
    assert out["skipped"] == "" and out["rounds"] == []
    files = league_files(world)
    assert "shadow_league.db" in files
    d = os.path.dirname(world.paths["agents"])
    assert os.path.exists(os.path.join(d, "shadow_league.db"))
    s = ST.Store(os.path.join(d, "shadow_league.db"))
    row = s.series("test", "BTC", "1h")
    assert row["status"] == "recording" and row["last_bar_ms"] is not None
    assert s.member("test")["activated_ms"] == QUIET
    assert s.feed("BTC", "1h")["n_ingested"] > 1000 and ex.requests
    assert open(world.paths["paper"], "rb").read() == paper_before                 # the paper accounts' file is untouched


def test_a_second_pass_continues_from_the_cursor_and_the_same_pass_twice_adds_nothing(world, monkeypatch):
    ex, member, t0 = league_exchange(hours=1700)
    monkeypatch.setattr(HK, "MEMBERS", (member,))
    pol = RM.RoomsPolicy(shadow_league=True)
    tick(world, pol, ex.get)
    d = os.path.join(os.path.dirname(world.paths["agents"]), "shadow_league.db")
    s = ST.Store(d)
    cur1 = s.series("test", "BTC", "1h")["last_bar_ms"]
    n1 = len(ex.requests)
    s.close()
    tick(world, pol, ex.get)                                                        # the same minute again
    assert len(ex.requests) == n1
    ex.now_ms += 5 * HOUR
    tick(world, pol, ex.get, now=QUIET + 5 * HOUR)
    s = ST.Store(d)
    assert s.series("test", "BTC", "1h")["last_bar_ms"] == cur1 + 5 * HOUR


def test_without_a_price_source_the_pass_goes_on_and_the_league_says_error(world, monkeypatch):
    ex, member, t0 = league_exchange()
    monkeypatch.setattr(HK, "MEMBERS", (member,))
    out = tick(world, RM.RoomsPolicy(shadow_league=True), None)                     # price_get=None, like the unit tests
    assert out["skipped"] == ""
    s = ST.Store(os.path.join(os.path.dirname(world.paths["agents"]), "shadow_league.db"))
    r = s.series("test", "BTC", "1h")
    assert r["status"] == "error" and "no price source" in r["note"]


def test_a_failing_league_never_stops_the_agents_pass(world, monkeypatch, capsys):
    monkeypatch.setattr(ST.Store, "__init__", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    out = tick(world, RM.RoomsPolicy(shadow_league=True), None)
    assert out["skipped"] == "" and out["rounds"] == []
    assert "disk full" in capsys.readouterr().err
    r = HK.run("/nonexistent/dir/agents3.db", QUIET, None)
    assert r["error"] and r["enabled"] is True


def test_a_broken_import_is_only_a_warning(world, monkeypatch, capsys):
    block_import(monkeypatch)
    out = tick(world, RM.RoomsPolicy(shadow_league=True), None)
    assert out["skipped"] == ""
    assert "shadow league failed" in capsys.readouterr().err


def test_the_wall_time_cap_is_at_most_twenty_seconds_and_is_handed_to_the_tick(world, monkeypatch):
    assert HK.WALL_S <= 20.0 and LG.WORK_S < LG.HARD_S <= 20.0
    seen = {}

    def fake_tick(self, now_ms, work_s=None, hard_s=None):
        seen.update(work_s=work_s, hard_s=hard_s)
        return {"errors": []}
    monkeypatch.setattr(LG.League, "tick", fake_tick)
    HK.run(world.paths["agents"], QUIET, None, members=(make_member(),))
    assert seen["hard_s"] <= 20.0 and seen["work_s"] < seen["hard_s"]


def test_the_agents_service_unit_is_unchanged():
    r = subprocess.run(["git", "-C", ROOT, "show", f"{BASE}:deploy/paperbot-agents.service"], capture_output=True)
    if r.returncode != 0:
        pytest.skip("the base commit is not in this clone")
    assert open(os.path.join(ROOT, "deploy", "paperbot-agents.service"), "rb").read() == r.stdout
    assert b"ReadWritePaths=/var/lib/paperbot" in r.stdout            # the league's file goes there: nothing to change


# ------------------------------------------------------------------------------------------------ template and docs
def test_the_env_template_has_the_line_commented_with_a_korean_note():
    env = open(os.path.join(ROOT, "deploy", "agents.env.example"), encoding="utf-8").read()
    assert "\n#AGENTS_SHADOW_LEAGUE=0\n" in env and "\nAGENTS_SHADOW_LEAGUE=" not in env
    lines = env.splitlines()
    i = lines.index("#AGENTS_SHADOW_LEAGUE=0")
    note = "\n".join(lines[i - 4:i])
    assert "그림자 리그" in note and "참고용, 판정 아님" in note and "docs/shadow-league.md" in note
    vals = dict(line[1:].split("=", 1) for line in lines
                if line.startswith("#AGENTS_") and "=" in line and line[1:].split("=", 1)[0] in RM.ENV_INTS)
    assert RM.policy_from_env({k: v for k, v in vals.items() if v}).shadow_league is False       # the documented value parses


def test_the_docs_say_what_a_shadow_account_is_and_are_linked_from_the_agent_rooms_doc():
    doc = open(os.path.join(ROOT, "docs", "shadow-league.md"), encoding="utf-8").read()
    for needle in ("그림자 계좌가 뭔가요", "331개", "절대 하지 않는 것", "켜는 법", "결과 읽는 법", "솔직한 기대", "실패",
                   "AGENTS_SHADOW_LEAGUE", "참고용, 판정 아님", "기술 메모", "shadow_league.db", "202d638e"):
        assert needle in doc, needle
    rooms = open(os.path.join(ROOT, "docs", "agent-rooms.md"), encoding="utf-8").read()
    assert rooms.count("AGENTS_SHADOW_LEAGUE") >= 3 and "docs/shadow-league.md" in rooms


# ------------------------------------------------------------------------------------------------ frozen files
def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True)


def _frozen_sets() -> dict:
    sets = {k: getattr(RI, k) for k in ("TRADING_FILES", "DS_FILES", "REEL_FILES", "EXTRA_FILES", "SHARED_SIGNAL_FILES",
                                        "RULES_FILES", "EXTRA_GATE_FILES", "STRENGTH_DEF_FILES")}
    return sets


def _frozen_path(p: str, listed: set) -> bool:
    b = posixpath.basename(p)
    return (p in listed or p.startswith("research/") or fnmatch.fnmatch(b, "*.sha256") or fnmatch.fnmatch(b, "checkpoint*.py")
            or b == "shadow200.py")


@pytest.fixture(scope="module")
def have_base():
    if _git("rev-parse", "--verify", f"{BASE}^{{commit}}").returncode != 0:
        pytest.skip("the base commit is not in this clone")


def test_the_runinfo_hash_of_every_frozen_set_equals_the_base_commit(have_base):
    for name, paths in _frozen_sets().items():
        h = hashlib.sha256()
        for rel in paths:
            r = _git("show", f"{BASE}:{rel}")
            h.update(rel.encode() + b"\0")
            h.update(r.stdout if r.returncode == 0 else b"<missing>")
        assert h.hexdigest() == RI.files_hash(paths), f"{name}: a frozen file differs from the base commit"
    assert RI.code_hashes()["trading_code"] == RI.files_hash(RI.TRADING_FILES)


def test_no_frozen_path_changed_since_the_base_commit(have_base):
    listed = {p for paths in _frozen_sets().values() for p in paths}
    changed = set(_git("diff", "--name-only", BASE).stdout.decode().split())                 # committed and uncommitted
    changed |= {ln[3:].strip() for ln in _git("status", "--porcelain", "-uall").stdout.decode().splitlines()}
    assert changed, "the branch changed nothing?"
    hits = sorted(p for p in changed if _frozen_path(p, listed))
    assert hits == [], hits
    assert any(p.startswith("paperbot/shadowleague/") for p in changed)


def test_no_frozen_python_file_imports_the_new_code():
    listed = {p for paths in _frozen_sets().values() for p in paths}
    files = {p for p in listed if p.endswith(".py")}
    for dirpath, _dirs, names in os.walk(os.path.join(ROOT, "research")):
        files |= {os.path.relpath(os.path.join(dirpath, n), ROOT) for n in names if n.endswith(".py")}
    files |= {"paperbot/" + n for n in os.listdir(os.path.join(ROOT, "paperbot")) if n.startswith("checkpoint") and n.endswith(".py")}
    files.add("paperbot/shadow200.py")
    seen = 0
    for rel in sorted(files):
        path = os.path.join(ROOT, rel)
        if os.path.exists(path):
            seen += 1
            assert "shadowleague" not in open(path, encoding="utf-8", errors="replace").read(), rel
    assert seen > 30


def test_nothing_the_live_runner_or_the_checkpoint_loads_imports_the_package():
    """The live runner's modules (TRADING_FILES and the group sets) never import paperbot.shadowleague."""
    import ast
    for rel in set(RI.TRADING_FILES) | set(RI.DS_FILES) | set(RI.REEL_FILES) | set(RI.EXTRA_FILES) | {"paperbot/live3.py"}:
        if rel.endswith(".py") and os.path.exists(os.path.join(ROOT, rel)):
            tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
            for node in ast.walk(tree):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                assert not [m for m in mods if "shadowleague" in m], rel
