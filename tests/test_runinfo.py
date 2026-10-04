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


def test_rules_files_include_change_1_and_match_their_hashes():
    """The rules change of 2026-10-04 (5m removed, restart from scratch) is part of the recorded rules text, and
    every rules document matches its fixed sha256 file (the same check launchcheck runs on the server)."""
    import hashlib
    from paperbot.launchcheck import RULES_SUMS
    from paperbot.runinfo import ROOT, RULES_FILES
    assert RULES_FILES == ("docs/paper-v3-rules.md", "docs/paper-v3-rules-addendum.md",
                           "docs/paper-v3-rules-change-1.md", "docs/levrule-eval.md")
    assert [p.replace(".md", ".sha256") for p in RULES_FILES] == list(RULES_SUMS)
    for rel in RULES_SUMS:
        with open(os.path.join(ROOT, rel)) as fh:
            rows = [r.split() for r in fh.read().splitlines() if r.strip()]
        assert len(rows) == 1 and rows[0][1] == rel.replace(".sha256", ".md")
        with open(os.path.join(ROOT, rows[0][1]), "rb") as fh:
            assert hashlib.sha256(fh.read()).hexdigest() == rows[0][0], rel
    a = run_record(v3_settings(), BR, "exchange", ["x"], signal_lock={"prereg_sha256_file": "L"})
    assert a["rules"] == files_hash(RULES_FILES)
    two = files_hash(RULES_FILES[:2])
    assert a["rules"] != two          # a start before the change file existed reads as a rules change


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


def test_update_doc_lists_the_trading_files():
    """docs/server-setup-v3.md 13-5 lists the files to diff before an update: the same set as TRADING_FILES (the
    strength definitions as their folder)."""
    import re
    from paperbot.runinfo import ROOT, STRENGTH_DEF_FILES
    with open(os.path.join(ROOT, "docs", "server-setup-v3.md"), encoding="utf-8") as fh:
        doc = fh.read()
    m = re.search(r"git diff --stat HEAD origin/\S+ -- \\\n(.*?)\n\s*```", doc, re.S)
    assert m, "the 13-5 git diff block is missing"
    listed = set(m.group(1).replace("\\", " ").split())
    want = (set(TRADING_FILES) - set(STRENGTH_DEF_FILES)) | {"research/entry_study/strength_defs"}
    assert listed == want
