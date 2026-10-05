import json
import os
import sqlite3

import pytest

from paperbot import Brackets
from paperbot.config import v3_settings
from paperbot.runinfo import TRADING_FILES, change_text, changes, code_version, files_hash, run_record
from paperbot.store3 import Store3

BR = {"BTCUSDT": Brackets.example()}


def test_run_record_is_stable_and_sees_setting_changes():
    a = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    b = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    assert changes(a, b) == [] and changes(None, a) == []
    c = run_record(v3_settings(taker_fee=0.0004), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    ch = changes(a, c)
    assert [x["key"] for x in ch] == ["settings"] and ch[0]["trading"]
    assert "오늘부터 다시 셈" in change_text(ch)


def test_commit_only_change_is_not_a_trading_change():
    a = {"commit": "1", "trading_code": "t", "settings": "s"}
    b = {"commit": "2", "trading_code": "t", "settings": "s"}
    txt = change_text(changes(a, b))
    assert "코드 버전" in txt and "영향 없음" in txt


def test_trading_files_hash_follows_content(tmp_path):
    for rel in TRADING_FILES:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    h1 = files_hash(TRADING_FILES, str(tmp_path))
    (tmp_path / "paperbot/ladder.py").write_text("y")
    assert files_hash(TRADING_FILES, str(tmp_path)) != h1


def test_version_file_wins_over_git(tmp_path):
    (tmp_path / "VERSION.json").write_text(json.dumps({"commit": "abc", "dirty": False, "tag": None}))
    assert code_version(str(tmp_path))["commit"] == "abc"
    assert code_version()["commit"]  # this checkout


def test_runs_table_is_append_only(tmp_path):
    st = Store3(str(tmp_path / "r.db"))
    assert st.last_run() is None
    st.add_run(1, {"commit": "a"})
    st.add_run(2, {"commit": "b"})
    st.commit()
    assert st.last_run() == {"commit": "b"}
    with pytest.raises(sqlite3.DatabaseError):
        st.conn.execute("UPDATE runs SET data = '{}'")
    with pytest.raises(sqlite3.DatabaseError):
        st.conn.execute("DELETE FROM runs")


def test_extra_watched_keys_and_text(tmp_path):
    from paperbot.runinfo import EXTRA_FILES, EXTRA_GATE_FILES, EXTRA_WATCHED, WATCHED
    a = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    assert a["extra_code"] == files_hash(EXTRA_FILES) and a["extra_gate_code"] == files_hash(EXTRA_GATE_FILES)
    assert [k for k, _, _ in EXTRA_WATCHED] == ["extra_code", "extra_gate_code"]
    assert not {k for k, _, _ in WATCHED} & {"extra_code", "extra_gate_code"}      # WATCHED applies to every account
    assert all(len(w) == 3 for w in WATCHED)                                          # checkpoint unpacks 3-tuples
    assert "paperbot/accounts.py" in TRADING_FILES and "paperbot/live3.py" in TRADING_FILES
    assert set(EXTRA_FILES) == {"paperbot/extras.py", "paperbot/newlab_live.py", "paperbot/agents/newlab_signals.py"}
    b = dict(a, extra_code="other")
    ch = changes(a, b)
    assert [(c["key"], c["trading"], c.get("extras_only")) for c in ch] == [("extra_code", True, True)]
    txt = change_text(ch)
    assert "추가 계좌만 해당" in txt and "원래 계좌의 코드는 그대로" in txt
    # the checkpoint does not restart the extras' windows for this: the text asks the rule keeper, as for others
    assert "30일을 다시 셀지 규칙 관리자 확인" in txt and "오늘부터 다시 셈" not in txt
    g = changes(a, dict(a, extra_gate_code="other"))
    assert [(c["key"], c["trading"]) for c in g] == [("extra_gate_code", False)] and "영향 없음" in change_text(g)
    both = changes(a, dict(a, extra_code="o", settings="o"))
    assert "오늘부터 다시 셈" in change_text(both) and "원래 계좌의 코드는" not in change_text(both)


def test_signal_input_code_shared_with_the_originals_is_never_called_extras_only(tmp_path):
    """recorder.py builds the originals' signal frames and context.py their chart context: a change to them is not an
    extras-only change, and the restart text never says the originals are unaffected (open question Q-11)."""
    import shutil
    from paperbot.runinfo import EXTRA_FILES, ROOT, SHARED_SIGNAL_FILES, SHARED_WATCHED, WATCHED
    assert set(SHARED_SIGNAL_FILES) == {"paperbot/recorder.py", "paperbot/context.py"}
    assert not set(SHARED_SIGNAL_FILES) & set(EXTRA_FILES)
    # Q-11 (decided before the first start): recorder.py builds the originals' signal frames, so it is trading code
    assert "paperbot/recorder.py" in TRADING_FILES and "paperbot/context.py" not in TRADING_FILES
    assert not {k for k, _, _ in WATCHED} & {k for k, _, _ in SHARED_WATCHED}
    # a change to recorder.py moves only the shared key
    for rel in SHARED_SIGNAL_FILES + EXTRA_FILES:
        os.makedirs(os.path.dirname(os.path.join(str(tmp_path), rel)), exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), os.path.join(str(tmp_path), rel))
    before = (files_hash(SHARED_SIGNAL_FILES, str(tmp_path)), files_hash(EXTRA_FILES, str(tmp_path)))
    with open(os.path.join(str(tmp_path), "paperbot", "recorder.py"), "a") as fh:
        fh.write("\n# changed\n")
    after = (files_hash(SHARED_SIGNAL_FILES, str(tmp_path)), files_hash(EXTRA_FILES, str(tmp_path)))
    assert after[0] != before[0] and after[1] == before[1]
    a = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    assert a["shared_signal_code"] == files_hash(SHARED_SIGNAL_FILES)
    ch = changes(a, dict(a, shared_signal_code="other"))
    assert [(c["key"], c["trading"], c.get("extras_only"), c.get("shared")) for c in ch] == \
        [("shared_signal_code", True, None, True)]
    txt = change_text(ch)
    assert "원래 계좌는 그대로" not in txt and "원래 계좌의 코드는 그대로" not in txt
    assert "추가 계좌만 해당" not in txt and "원래 계좌의 신호 계산" in txt and "Q-11" in txt
    # a record written before the key existed is not a change
    old = {k: v for k, v in a.items() if k != "shared_signal_code"}
    assert changes(old, a) == []


V3_RULES = ("docs/paper-v3-rules.md", "docs/paper-v3-rules-addendum.md", "docs/paper-v3-rules-change-1.md",
            "docs/levrule-eval.md")
V4_RULES = ("docs/paper-v4-rules.md", "docs/paper-v4-verdict.md", "docs/levrule-eval-v4.md")


def test_rules_files_include_change_1_and_the_v4_documents():
    """The rules change of 2026-10-04 (5m removed, restart from scratch) and the three paper v4 documents (plan
    section 6: rules, verdict method, rule B's v4 population) are part of the recorded rules text. The v3 documents
    stay: the v4 rules carry them over by sha256."""
    from paperbot.runinfo import RULES_FILES
    assert RULES_FILES == V3_RULES + V4_RULES
    a = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    assert a["rules"] == files_hash(RULES_FILES)
    assert a["rules"] != files_hash(RULES_FILES[:2])     # a start before the change file existed reads as a change
    assert a["rules"] != files_hash(V3_RULES)            # so does one before the v4 documents existed


def test_rules_files_match_launchcheck_and_their_hashes():
    """Every rules document matches its fixed sha256 file (the same check launchcheck runs on the server), and
    launchcheck checks exactly these. Needs P0-doc's three hashed v4 documents and P12's RULES_SUMS."""
    import hashlib
    from paperbot.launchcheck import RULES_SUMS
    from paperbot.runinfo import ROOT, RULES_FILES
    missing = [f for doc in RULES_FILES for f in (doc, doc.replace(".md", ".sha256"))
               if not os.path.exists(os.path.join(ROOT, f))]
    assert not missing, f"rules documents or their .sha256 files missing (P0-doc): {missing}"
    assert [p.replace(".md", ".sha256") for p in RULES_FILES] == list(RULES_SUMS), "launchcheck.RULES_SUMS (P12)"
    for rel in RULES_SUMS:
        with open(os.path.join(ROOT, rel)) as fh:
            rows = [r.split() for r in fh.read().splitlines() if r.strip()]
        assert len(rows) == 1 and rows[0][1] == rel.replace(".sha256", ".md")
        with open(os.path.join(ROOT, rows[0][1]), "rb") as fh:
            assert hashlib.sha256(fh.read()).hexdigest() == rows[0][0], rel


def test_trading_files_cover_what_decides_leverage_and_the_feed(tmp_path):
    """Review M1: the strength definitions decide each signal's leverage group (quality_v1), and binance.py builds
    the feed's bars. Editing a definition changes the trading-code hash even when the lock file is left alone."""
    import shutil
    from paperbot.entry_marks import locked_defs
    from paperbot.runinfo import ROOT, STRENGTH_DEF_FILES
    for rel in ("research/entry_study/DEFS_BC.sha256", "paperbot/binance.py", "paperbot/p_best_cells.json",
                "paperbot/levrule.py", "paperbot/quality_edges.json", "paperbot/entry_marks.py"):
        assert rel in TRADING_FILES and os.path.exists(os.path.join(ROOT, rel))
    locked = {"research/entry_study/" + rel for rel in locked_defs() if rel.startswith("strength_defs/")}
    assert locked and locked <= set(STRENGTH_DEF_FILES) <= set(TRADING_FILES)
    assert all(os.path.exists(os.path.join(ROOT, rel)) for rel in TRADING_FILES)
    assert len(set(TRADING_FILES)) == len(TRADING_FILES)
    for rel in TRADING_FILES:
        os.makedirs(os.path.dirname(os.path.join(str(tmp_path), rel)), exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), os.path.join(str(tmp_path), rel))
    h0 = files_hash(TRADING_FILES, str(tmp_path))
    assert h0 == files_hash(TRADING_FILES)
    with open(os.path.join(str(tmp_path), "research/entry_study/strength_defs/N01_ST_EMA.py"), "a") as fh:
        fh.write("\n# edited\n")
    h1 = files_hash(TRADING_FILES, str(tmp_path))
    assert h1 != h0
    with open(os.path.join(str(tmp_path), "research/entry_study/DEFS_BC.sha256"), "a") as fh:
        fh.write("\n")
    assert files_hash(TRADING_FILES, str(tmp_path)) not in (h0, h1)
    with open(os.path.join(str(tmp_path), "paperbot/binance.py"), "a") as fh:
        fh.write("\n# edited\n")
    assert files_hash(TRADING_FILES, str(tmp_path)) not in (h0, h1)


def test_coin_flip_rate_file_is_a_trading_file(tmp_path):
    """Review 3a F3: research/paper_rules/out/summary.json["random_rate"] is every live coin-flip account's fire
    rate (live3.random_rates); a research re-run rewrites it in place, so it must change the trading-code hash."""
    import shutil
    from paperbot.live3 import RANDOM_RATES, random_rates
    from paperbot.runinfo import ROOT
    rel = "research/paper_rules/out/summary.json"
    assert rel in TRADING_FILES and os.path.samefile(os.path.join(ROOT, rel), RANDOM_RATES)
    for r in TRADING_FILES:
        os.makedirs(os.path.dirname(os.path.join(str(tmp_path), r)), exist_ok=True)
        shutil.copy(os.path.join(ROOT, r), os.path.join(str(tmp_path), r))
    h0 = files_hash(TRADING_FILES, str(tmp_path))
    p = os.path.join(str(tmp_path), rel)
    with open(p) as fh:
        doc = json.load(fh)
    doc["random_rate"]["15m"] *= 2
    with open(p, "w") as fh:
        json.dump(doc, fh)
    assert random_rates(p)["15m"] == 2 * random_rates()["15m"]
    assert files_hash(TRADING_FILES, str(tmp_path)) != h0


def _diff_block(doc_path):
    import re
    with open(doc_path, encoding="utf-8") as fh:
        doc = fh.read()
    m = re.search(r"git diff --stat HEAD origin/\S+ -- \\\n(.*?)\n\s*```", doc, re.S)
    return None if not m else set(m.group(1).replace("\\", " ").split())


def test_update_doc_lists_the_trading_files():
    """docs/server-setup-v3.md 13-5 lists the files to diff before an update: the v3 trading files (the strength
    definitions as their folder). Paper v4 added paperbot/sweepsig.py to the shared set; the v3 guide stays as it
    was."""
    from paperbot.runinfo import ROOT, STRENGTH_DEF_FILES
    listed = _diff_block(os.path.join(ROOT, "docs", "server-setup-v3.md"))
    assert listed is not None, "the 13-5 git diff block is missing"
    want = (set(TRADING_FILES) - set(STRENGTH_DEF_FILES) - {"paperbot/sweepsig.py"}) | \
        {"research/entry_study/strength_defs"}
    assert listed == want


def test_v4_update_doc_lists_every_hashed_file():
    """docs/server-setup-v4.md (P12), when it carries the same "git diff --stat HEAD origin/<branch> --" block, lists
    every Q5-hashed file of every group: the shared set and the DeepSeek and reel sets."""
    import pytest
    from paperbot.runinfo import DS_FILES, REEL_FILES, ROOT, STRENGTH_DEF_FILES
    path = os.path.join(ROOT, "docs", "server-setup-v4.md")
    listed = _diff_block(path) if os.path.exists(path) else None
    if listed is None:
        pytest.skip("docs/server-setup-v4.md has no update diff block (yet)")
    want = (set(TRADING_FILES + DS_FILES + REEL_FILES) - set(STRENGTH_DEF_FILES)) | \
        {"research/entry_study/strength_defs"}
    assert listed == want


# ---------------------------------------------------------------- paper v4: one Q5 hash per group (owners' D8)
DS_WANT = {"paperbot/dssig.py", "paperbot/ds_pins.json", "research/deepseek200/lib_c.py",
           "research/deepseek200/PREREG_DEEPSEEK200.sha256", "research/library/lib.py", "research/search/search.py"}
REEL_WANT = {"paperbot/reelsig.py", "paperbot/reel_engine.py", "research/reel5m/lib_reel5m.py",
             "research/reel5m/PREREG_REEL5M.sha256", "research/library/lib.py", "research/search/search.py"}


def test_group_sets_are_the_decided_files_and_apart_from_the_shared_set():
    from paperbot import runinfo as R
    from paperbot.accounts import GROUP_OF_KIND
    from paperbot.groups import GROUPS
    assert "paperbot/sweepsig.py" in R.TRADING_FILES                         # plan P6: today's set + sweepsig.py
    assert set(R.DS_FILES) == DS_WANT and set(R.REEL_FILES) - {"paperbot/reel_pins.json"} == REEL_WANT
    assert R.GROUP_FILES == {"ds200": R.DS_FILES, "reel": R.REEL_FILES}
    # research/library/lib.py and research/search/search.py: lib_c.env() and lib_reel5m.env() both load them
    assert set(R.DS_FILES) & set(R.REEL_FILES) == {"research/library/lib.py", "research/search/search.py"}
    for files in (R.DS_FILES, R.REEL_FILES):
        assert len(set(files)) == len(files)
        assert all(os.path.exists(os.path.join(R.ROOT, f)) for f in files), files
        for other in ("TRADING_FILES", "EXTRA_FILES", "EXTRA_GATE_FILES", "SHARED_SIGNAL_FILES", "RULES_FILES"):
            assert not set(files) & set(getattr(R, other)), other
    hashed = set(R.TRADING_FILES + R.DS_FILES + R.REEL_FILES + R.EXTRA_FILES + R.EXTRA_GATE_FILES
                 + R.SHARED_SIGNAL_FILES + R.RULES_FILES)
    # display-only and shadow code never restart a window; the research outputs are not code
    for f in ("paperbot/groups.py", "paperbot/shadow200.py", "research/deepseek200/out/summary.json",
              "research/deepseek200/FORWARD_PREREG.md"):
        assert f not in hashed and f not in R.NOT_HASHED
    assert not set(R.NOT_HASHED) & hashed
    # every pin file of the live wrappers is hashed with its group
    pins = {"paperbot/" + f for f in os.listdir(os.path.join(R.ROOT, "paperbot")) if f.endswith("_pins.json")}
    assert "paperbot/ds_pins.json" in pins and pins <= set(R.DS_FILES + R.REEL_FILES)
    # the keys: kept apart from WATCHED (every account), the extras' and the shared signal keys
    assert [k for k, _, _ in R.GROUP_WATCHED] == ["ds_code", "reel_code"]
    assert all(len(w) == 3 and w[2] is True for w in R.GROUP_WATCHED)
    gk = {k for k, _, _ in R.GROUP_WATCHED}
    for other in (R.WATCHED, R.EXTRA_WATCHED, R.SHARED_WATCHED):
        assert not gk & {k for k, _, _ in other}
    assert R.GROUP_OF_KEY == {"ds_code": "ds200", "reel_code": "reel"}
    assert set(R.GROUP_OF_KEY.values()) <= set(GROUP_OF_KIND.values())
    assert R.ALL_GROUPS == GROUPS and set(R.ALL_GROUPS) == set(GROUP_OF_KIND.values())
    assert set(R.GROUP_ONLY_KO) == set(R.GROUP_OF_KEY.values())


def _copy_tree(tmp_path):
    import shutil
    from paperbot import runinfo as R
    for rel in set(R.TRADING_FILES + R.DS_FILES + R.REEL_FILES + R.RULES_FILES + R.EXTRA_FILES
                   + R.SHARED_SIGNAL_FILES + R.EXTRA_GATE_FILES):
        src = os.path.join(R.ROOT, rel)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.join(str(tmp_path), rel)), exist_ok=True)
            shutil.copy(src, os.path.join(str(tmp_path), rel))
    return str(tmp_path)


def test_one_byte_moves_only_its_own_key(tmp_path):
    """D8: a DeepSeek-only or reel-only fix changes only that group's key; a shared file changes the shared key."""
    from paperbot.runinfo import code_hashes
    root = _copy_tree(tmp_path)
    h0 = code_hashes(root)
    assert h0 == code_hashes()               # the copy holds every file of every set
    cases = {"research/deepseek200/lib_c.py": {"ds_code"},
             "paperbot/dssig.py": {"ds_code"},
             "paperbot/ds_pins.json": {"ds_code"},
             "research/deepseek200/PREREG_DEEPSEEK200.sha256": {"ds_code"},
             "paperbot/reelsig.py": {"reel_code"},
             "paperbot/reel_engine.py": {"reel_code"},
             "research/reel5m/lib_reel5m.py": {"reel_code"},
             "research/reel5m/PREREG_REEL5M.sha256": {"reel_code"},
             "research/library/lib.py": {"ds_code", "reel_code"},
             "research/search/search.py": {"ds_code", "reel_code"},
             "paperbot/engine.py": {"trading_code"},
             "paperbot/policy.py": {"trading_code"},
             "paperbot/models.py": {"trading_code"},
             "paperbot/config.py": {"trading_code"},
             "paperbot/sweepsig.py": {"trading_code"},
             "paperbot/sigservice.py": {"trading_code"},
             "paperbot/recorder.py": {"trading_code", "shared_signal_code"},
             "paperbot/extras.py": {"extra_code"},
             "docs/levrule-eval.md": {"rules"}}
    for rel, keys in cases.items():
        p = os.path.join(root, rel)
        with open(p, "rb") as fh:
            before = fh.read()
        with open(p, "ab") as fh:
            fh.write(b"\n")
        h1 = code_hashes(root)
        assert {k for k in h0 if h0[k] != h1[k]} == keys, rel
        with open(p, "wb") as fh:
            fh.write(before)
        assert code_hashes(root) == h0
    # a missing group file is a change too (it hashes as "<missing>")
    os.remove(os.path.join(root, "paperbot/reel_engine.py"))
    h2 = code_hashes(root)
    assert {k for k in h0 if h0[k] != h2[k]} == {"reel_code"}


def test_group_changes_restart_only_their_group():
    from paperbot.runinfo import (ALL_GROUPS, DS_FILES, REEL_FILES, WATCHED, groups_hit)
    a = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    assert a["ds_code"] == files_hash(DS_FILES) and a["reel_code"] == files_hash(REEL_FILES)
    assert a["settings_version"] == "paper-v4" and "group_locks" not in a
    # the checkpoint counts WATCHED trading keys as every account's change: the group keys are never among them
    assert not {k for k, _, t in WATCHED if t} & {"ds_code", "reel_code"}

    ds = changes(a, dict(a, ds_code="other"))
    assert [(c["key"], c["trading"], c.get("group"), c.get("extras_only"), c.get("shared")) for c in ds] == \
        [("ds_code", True, "ds200", None, None)]
    t = change_text(ds)
    assert t.startswith("재시작 변경 · 딥시크 그룹만 영향") and "딥시크 신호 코드(딥시크만 해당)" in t
    assert "딥시크 계좌의 30일 기간만 오늘부터 다시 셈" in t and "잠긴 매매법 36개·다른 그룹은 그대로" in t
    assert "모든 그룹" not in t and "5분" not in t
    assert groups_hit([c["key"] for c in ds]) == ("ds200",)

    reel = changes(a, dict(a, reel_code="other"))
    assert [(c["key"], c.get("group")) for c in reel] == [("reel_code", "reel")]
    t = change_text(reel)
    assert t.startswith("재시작 변경 · 5분 단타 그룹만 영향") and "5분 동전 3개도" in t and "딥시크" not in t
    assert groups_hit(["reel_code"]) == ("reel",)

    both = changes(a, dict(a, ds_code="o", reel_code="o", extra_code="o"))
    t = change_text(both)
    assert t.startswith("재시작 변경 · 딥시크·5분 단타 그룹만 영향") and "추가 계좌 코드도 바뀜" in t
    assert groups_hit([c["key"] for c in both]) == ("ds200", "reel", "extra")
    t = change_text(changes(a, dict(a, ds_code="o", shared_signal_code="o")))
    assert "딥시크 그룹만 영향" in t and "recorder·context" in t and "Q-11" in t

    # a shared trading change wins: every group's window
    sh = changes(a, dict(a, ds_code="o", trading_code="o"))
    t = change_text(sh)
    assert "거래 규칙 영향 있음" in t and "모든 그룹의 30일 기간을 오늘부터 다시 셈" in t
    assert groups_hit([c["key"] for c in sh]) == ALL_GROUPS
    for k in ("settings", "brackets", "signal_code"):
        assert groups_hit([k]) == ALL_GROUPS
    assert groups_hit(["commit", "packages", "rules", "extra_gate_code"]) == () and groups_hit(None) == ()
    assert groups_hit(["extra_code"]) == ("extra",) and groups_hit(["shared_signal_code"]) == ("extra",)

    # the v4 run starts with every group key: a record without one cannot prove the code did not change
    old = {k: v for k, v in a.items() if k != "reel_code"}
    assert [c["key"] for c in changes(old, a)] == ["reel_code"]
    # what the pin checks gave is recorded, JSON-clean, and not watched
    g = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"},
                   group_locks={"ds200": {"lib_c.py": "abc"}, "reel": {"refused": ValueError("pin")}})
    assert g["group_locks"] == {"ds200": {"lib_c.py": "abc"}, "reel": {"refused": "pin"}}
    assert changes(a, g) == [] and json.loads(json.dumps(g)) == g


_GRAPH_CHILD = r'''
import importlib.util, json, os, sys
root = sys.argv[1]
sys.path.insert(0, root)
import paperbot.live3, paperbot.sigservice, paperbot.accounts, paperbot.recorder, paperbot.entry_marks  # noqa
import paperbot.dssig, paperbot.reelsig, paperbot.reel_engine  # noqa
from paperbot import sweepsig
sweepsig.lib()
for mod in ("paperbot.dssig", "paperbot.reelsig"):      # the wrappers' own contained loads, when implemented
    try:
        sys.modules[mod].verify()
    except BaseException:
        pass
# the research code the wrappers load by path, loaded here directly so the graph does not depend on their state
for name, rel in (("_g_lib_c", "research/deepseek200/lib_c.py"), ("_g_reel", "research/reel5m/lib_reel5m.py")):
    spec = importlib.util.spec_from_file_location(name, os.path.join(root, rel))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    m.env()
real = os.path.realpath(root) + os.sep
files = set()
for m in list(sys.modules.values()):
    f = getattr(m, "__file__", None)
    if f and os.path.realpath(f).startswith(real):
        files.add(os.path.relpath(os.path.realpath(f), os.path.realpath(root)))
print(json.dumps(sorted(files)))
'''


def _static_imports(root, rel):
    """Repository files one module imports anywhere in its body (function-level imports too)."""
    import ast
    tree = ast.parse(open(os.path.join(root, rel), encoding="utf-8").read())
    pkg = os.path.dirname(rel)
    bare_dirs = ("", "research/search", "third_party/sweep/harness", "third_party/sweep/harness/vendor")
    out = set()
    for n in ast.walk(tree):
        cands = []
        if isinstance(n, ast.ImportFrom) and n.level:
            base = pkg
            for _ in range(n.level - 1):
                base = os.path.dirname(base)
            mod = os.path.join(base, *(n.module or "").split(".")) if n.module else base
            cands = [mod] + [os.path.join(mod, a.name) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mod = (n.module or "").replace(".", "/")
            cands = [os.path.join(d, mod) for d in bare_dirs] + \
                [os.path.join(d, mod, a.name) for d in bare_dirs for a in n.names]
        elif isinstance(n, ast.Import):
            cands = [os.path.join(d, a.name.replace(".", "/")) for d in bare_dirs for a in n.names]
        for c in cands:
            for p in (c + ".py", os.path.join(c, "__init__.py")):
                if os.path.isfile(os.path.join(root, p)):
                    out.add(os.path.normpath(p))
    return out


def test_every_module_on_the_trading_path_is_classified():
    """Plan risk 8 (Q5 attribution): every repository file the live runner imports (the runner, the signal service,
    the engines, the DeepSeek and reel wrappers and the research code they load by path), and every repository file
    any hashed module imports anywhere in its body, is hashed in exactly one place (the shared set, a group set, an
    extras set; lib.py / search.py in both group sets), locked by third_party/sweep/PREREG.sha256 (the
    "signal_code" key; sweepsig.verify() refuses a changed file), or listed in runinfo.NOT_HASHED with a reason."""
    import subprocess
    import sys
    from paperbot import runinfo as R
    with open(os.path.join(R.ROOT, "third_party", "sweep", "PREREG.sha256")) as fh:
        locked = {"third_party/sweep/" + ln.split(None, 1)[1].strip() for ln in fh if ln.strip()}
    sets = {"shared": set(R.TRADING_FILES), "ds200": set(R.DS_FILES), "reel": set(R.REEL_FILES),
            "extra": set(R.EXTRA_FILES), "extra_gate": set(R.EXTRA_GATE_FILES),
            "shared_signal": set(R.SHARED_SIGNAL_FILES), "locked": locked, "not_hashed": set(R.NOT_HASHED)}

    def homes(f):
        return {name for name, files in sets.items() if f in files}

    out = subprocess.run([sys.executable, "-c", _GRAPH_CHILD, R.ROOT], capture_output=True, text=True,
                         timeout=600, cwd=R.ROOT)
    assert out.returncode == 0, out.stderr[-3000:]
    dynamic = set(json.loads(out.stdout.strip().splitlines()[-1]))
    for must in ("paperbot/live3.py", "paperbot/engine.py", "paperbot/dssig.py", "paperbot/reelsig.py",
                 "paperbot/reel_engine.py", "research/deepseek200/lib_c.py", "research/reel5m/lib_reel5m.py",
                 "research/library/lib.py", "research/search/search.py", "paperbot/sweepsig.py"):
        assert must in dynamic, must
    static = set()
    todo = [f for f in set(R.TRADING_FILES + R.DS_FILES + R.REEL_FILES) if f.endswith(".py")]
    seen = set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for g in _static_imports(R.ROOT, f):
            static.add(g)
            if g in sets["shared"] | sets["ds200"] | sets["reel"]:
                todo.append(g)            # follow the hashed modules only; the others are classified leaves
    unclassified = sorted(f for f in dynamic | static if not homes(f))
    assert not unclassified, ("on the trading path but in no hash set and not in runinfo.NOT_HASHED: "
                              f"{unclassified}")
    # exactly one home, except the two library files both groups load and recorder.py (Q-11)
    ok_twice = {"research/library/lib.py": {"ds200", "reel"}, "research/search/search.py": {"ds200", "reel"},
                "paperbot/recorder.py": {"shared", "shared_signal"}}
    for f in dynamic | static:
        assert len(homes(f)) == 1 or homes(f) == ok_twice.get(f), (f, homes(f))
    # nothing listed as unhashed is in fact on no path at all (a stale entry hides nothing, but keep the list honest)
    assert set(R.NOT_HASHED) <= dynamic | static
