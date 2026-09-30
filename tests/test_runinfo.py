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
