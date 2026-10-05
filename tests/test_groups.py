"""paperbot/groups.py: the display-only group table of the paper v4 run."""

import os
import re
import sqlite3

from paperbot import Brackets
from paperbot import config as C
from paperbot import groups as G
from paperbot.accounts import GROUP_OF_KIND, ORIGINAL_KINDS, AccountBook
from paperbot.store3 import Store3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = [f"S{k:02d}" for k in range(36)]


def test_groups_cover_every_kind():
    assert G.ORIGINAL_GROUPS == tuple(C.V4_GROUPS) and set(G.GROUPS) == set(G.ORIGINAL_GROUPS) | {"extra"}
    assert set(GROUP_OF_KIND.values()) == set(G.GROUPS)
    assert {GROUP_OF_KIND[k] for k in ORIGINAL_KINDS} == set(G.ORIGINAL_GROUPS)
    assert set(G.GROUP_KO) == set(G.GROUP_LONG_KO) == set(G.GROUPS)
    assert G.group_of({"kind": "ds200"}) == "ds200" and G.group_of({"kind": "reel"}) == "reel"
    assert G.group_of({"kind": "strategy"}) == "core" and G.group_of({"kind": "random"}) == "flip"
    assert G.group_of({"kind": "copy"}) == G.group_of({"kind": "newlab"}) == "extra"
    assert G.group_of({"kind": "something_new"}) == "other" and G.group_of({}) == "other"
    # owners' D10: per-trade Telegram for core, reel and extras; DeepSeek and the coin flips counted only
    assert set(G.TRADE_ALERT_GROUPS) | set(G.COUNT_ONLY_GROUPS) == set(G.GROUPS)
    assert not set(G.TRADE_ALERT_GROUPS) & set(G.COUNT_ONLY_GROUPS) and "ds200" in G.COUNT_ONLY_GROUPS
    assert G.DEFAULT_SHOWN_GROUPS == ("core", "reel")


def test_family_names_are_the_preregs():
    assert set(G.DS_FAMILY_KO) == set(C.DS200_FAMILY.values()) == {f"F{k}" for k in range(1, 18)}
    text = open(os.path.join(ROOT, "research", "deepseek200", "PREREG_DEEPSEEK200.md"), encoding="utf-8").read()
    heads = dict(re.findall(r"^### (F\d+) (.+?) \(\d+개", text, flags=re.M))
    assert heads == G.DS_FAMILY_KO
    assert G.family_of({"kind": "ds200", "strategy": "F9_FVG", "data": '{"family": "F9"}'}) == "F9"
    assert G.family_of({"kind": "ds200", "strategy": "F9_FVG", "data": None}) == "F9"
    assert G.family_of({"kind": "strategy", "strategy": "V45_AMB"}) is None


def test_five_new_specialist_roles():
    assert [k for k, *_ in G.V4_ROLES] == ["ds_structure", "ds_trend", "ds_session", "ds_reversal", "reel_5m"]
    assert [ko for _k, ko, *_ in G.V4_ROLES] == ["구조·유동성 담당", "추세·눌림 담당", "세션·시가 담당",
                                                 "반전·되돌림 담당", "5분봉 단타 담당"]
    every = [G.role_of(d) for d in C.DS200_IDS]
    assert None not in every                                   # every DeepSeek definition has exactly one role
    members = {k: G.role_members(k) for k in G.ROLE_KO}
    assert sorted(sum(members.values(), [])) == sorted(list(C.DS200_IDS) + [C.REEL_NAME])
    assert G.role_of("F11_PO3") == "ds_session" and G.role_of("F15_ORB") == "ds_session"
    assert G.role_of("F11_RAID") == G.role_of("F14_SMT") == "ds_structure"
    assert G.role_of("F7_RF_ONLY") == "ds_trend" and G.role_of("F17_Z") == "ds_reversal"
    assert members["reel_5m"] == [C.REEL_NAME] and G.role_of("V45_AMB") is None
    assert len(members["ds_session"]) == 7 and len(members["ds_trend"]) == 7


def test_labels():
    assert G.label_ko("F9_FVG", "15m") == "딥시크 F9_FVG (FVG·오더 블록)"
    assert G.label_ko(C.REEL_NAME, "5m") == G.REEL_KO
    assert G.label_ko("RANDOM_2", "5m").endswith(" 2") and G.label_ko("RANDOM_2", "15m") is None
    assert G.label_ko("V45_AMB", "15m") is None


def test_shape_from_db_v4_and_v3(tmp_path):
    book = AccountBook(C.v3_settings(), {s: Brackets.example() for s in C.V3_SYMBOLS},
                       Store3(str(tmp_path / "v4.db")))
    book.open_accounts(C.v4_account_defs(CORE), 0)
    book.store.add_account("S00@15m~c1", "S00", "15m", "copy", 1, "paper-v4", "S00@15m", {"v": 1})
    book.store.commit()
    sh = G.shape_from_db(book.store.conn)
    assert sh["accounts"] == 332 and sh["originals"] == 331 and sh["versions"] == ["paper-v4"]
    assert list(sh["groups"]) == ["core", "ds200", "reel", "flip", "extra"]
    assert {g: v["accounts"] for g, v in sh["groups"].items()} == {**C.V4_GROUP_ACCOUNTS, "extra": 1}
    assert {g: v["judged"] for g, v in sh["groups"].items()} == {**C.V4_GROUP_JUDGED, "extra": 0}
    assert sh["groups"]["reel"]["tfs"] == {"5m": 1} and sh["groups"]["flip"]["tfs"]["5m"] == 3
    assert sh["tfs"]["5m"] == 4 and sh["tfs"]["15m"] == 84
    # a v3-shaped database reads as 156 core + flip accounts
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE accounts (account_id, strategy, timeframe, kind, created_ts, settings_version, parent, "
              "data)")
    for tf in C.V3_TRADE_TFS:
        for s in CORE:
            c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", (f"{s}@{tf}", s, tf, "strategy", 0, "paper-v3",
                                                                       None, "{}"))
        for k in (1, 2, 3):
            c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", (f"RANDOM_{k}@{tf}", f"RANDOM_{k}", tf, "random",
                                                                       0, "paper-v3", None, "{}"))
    sh3 = G.shape_from_db(c)
    assert sh3["accounts"] == 156 and sh3["versions"] == ["paper-v3"]
    assert {g: v["accounts"] for g, v in sh3["groups"].items()} == {"core": 144, "flip": 12}
    assert sh3["groups"]["core"]["judged"] == 108


def test_groups_is_not_a_trading_file():
    from paperbot import runinfo
    rel = "paperbot/groups.py"
    for files in (runinfo.TRADING_FILES, runinfo.EXTRA_FILES, runinfo.RULES_FILES, runinfo.SHARED_SIGNAL_FILES):
        assert rel not in files
    # nothing on the trading path imports it
    for f in runinfo.TRADING_FILES:
        if f.startswith("paperbot/") and f.endswith(".py"):
            src = open(os.path.join(ROOT, f), encoding="utf-8").read()
            assert not re.search(r"^\s*(from \.groups|from paperbot\.groups|import paperbot\.groups|from \. import "
                                 r"groups)", src, flags=re.M), f
