import json
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
    assert "다시 셉니다" in change_text(ch)


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
    assert set(EXTRA_FILES) == {"paperbot/extras.py", "paperbot/newlab_live.py", "paperbot/agents/newlab_signals.py",
                                "paperbot/context.py", "paperbot/recorder.py"}
    b = dict(a, extra_code="other")
    ch = changes(a, b)
    assert [(c["key"], c["trading"], c.get("extras_only")) for c in ch] == [("extra_code", True, True)]
    txt = change_text(ch)
    assert "추가 계좌만 해당" in txt and "원래 195개 계좌는 그대로" in txt
    g = changes(a, dict(a, extra_gate_code="other"))
    assert [(c["key"], c["trading"]) for c in g] == [("extra_gate_code", False)] and "영향 없음" in change_text(g)
    both = changes(a, dict(a, extra_code="o", settings="o"))
    assert "다시 셉니다" in change_text(both) and "원래 195개" not in change_text(both)
