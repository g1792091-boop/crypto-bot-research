"""The paper v4 run shape (plan P1, docs/paper-v4-rules.md): 331 accounts in four groups, the kinds, the engine each
account is built with, and the interfaces of the new signal and exit modules."""

import inspect
import json
import os
import subprocess
import sys

import pytest

from paperbot import Brackets, Signal
from paperbot import config as C
from paperbot.accounts import (GROUP_OF_KIND, ORIGINAL_KINDS, AccountBook, HeldEngine, exits_of, hold_others,
                               original_engine_cls)
from paperbot.engine import PaperEngine
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = C.v3_settings()
CORE = [f"S{k:02d}" for k in range(36)]
SESSION_DEFS = ("F15_ASIA_BRK", "F15_ASIA_SWEEP", "F15_LON_BRK", "F15_OPEN0930", "F15_OPEN0000")


def _book(path, notifier=None):
    return AccountBook(S, {s: Brackets.example() for s in C.V3_SYMBOLS}, Store3(str(path)), notifier)


# ------------------------------------------------------------------ counts
def test_331_accounts_in_four_groups():
    assert C.V4_ACCOUNTS == 331
    assert C.V4_GROUP_ACCOUNTS == {"core": 144, "ds200": 171, "reel": 1, "flip": 15}
    assert C.V4_TF_ACCOUNTS == {"5m": 4, "15m": 83, "30m": 83, "1h": 83, "4h": 78}
    assert C.V4_GROUP_JUDGED == {"core": 108, "ds200": 132, "reel": 1, "flip": 0}
    assert C.V4_JUDGED_ACCOUNTS == 241
    assert C.V4_GROUP_TF_COUNTS["ds200"] == {"15m": 44, "30m": 44, "1h": 44, "4h": 39}
    # the v3 names keep their values and mean the core group (156 = 144 + 12 coin flips, judged 108)
    assert C.V3_ACCOUNTS == 156 and C.V3_Q1_MAIN_FAMILY == 108 and C.V3_STRATEGIES == 36
    assert C.V3_TRADE_TFS == ("15m", "30m", "1h", "4h") and "5m" not in C.V3_TRADE_TFS
    assert C.V3_JUDGED_TFS == ("15m", "30m", "1h") and C.V3_OBSERVE_TFS == ("4h",)


def test_account_defs_shape():
    defs = C.v4_account_defs(CORE)
    assert len(defs) == C.V4_ACCOUNTS == 331
    assert len({(d["strategy"], d["timeframe"]) for d in defs}) == 331
    by = lambda g: [d for d in defs if d["data"]["group"] == g]  # noqa: E731
    assert not [d for d in by("core") + by("ds200") if d["timeframe"] == "5m"]       # no core or DS account on 5m
    assert [(d["strategy"], d["timeframe"]) for d in by("reel")] == [("REEL_H1", "5m")]
    assert not [d for d in defs if d["strategy"] == C.REEL_NAME and d["timeframe"] != "5m"]
    assert not [d for d in defs if d["strategy"] in SESSION_DEFS and d["timeframe"] == "4h"]
    assert {d["timeframe"] for d in defs if d["strategy"] in SESSION_DEFS} == {"15m", "30m", "1h"}
    assert {d["timeframe"] for d in defs if d["strategy"] == "F15_ORB"} == {"15m", "30m", "1h", "4h"}
    assert sorted((d["strategy"], d["timeframe"]) for d in by("flip")) == sorted(
        (f"RANDOM_{k}", tf) for k in (1, 2, 3) for tf in ("5m", "15m", "30m", "1h", "4h"))
    for d in defs:
        g = d["data"]["group"]
        assert d["kind"] == C.V4_GROUPS[g]["kind"] and GROUP_OF_KIND[d["kind"]] == g
        assert set(d["data"]) == {"group", "family", "exits"}
        assert d["data"]["family"] == (C.DS200_FAMILY[d["strategy"]] if g == "ds200" else None)
        want = "reel" if g == "reel" or (g == "flip" and d["timeframe"] == "5m") else "house"
        assert d["data"]["exits"] == want == C.v4_exits(d["kind"], d["timeframe"])
    per_tf = {}
    for d in defs:
        per_tf[d["timeframe"]] = per_tf.get(d["timeframe"], 0) + 1
    assert per_tf == C.V4_TF_ACCOUNTS
    with pytest.raises(ValueError):
        C.v4_account_defs(CORE[:35])
    with pytest.raises(ValueError):
        C.v4_account_defs(CORE[:35] + CORE[:1])


def test_first_156_are_the_v3_accounts_in_v3_order():
    from paperbot.live3 import account_defs
    from paperbot.sigservice import TRADE_TFS
    v3 = account_defs(CORE, TRADE_TFS)
    v4 = C.v4_account_defs(CORE)
    assert [(d["strategy"], d["timeframe"], d["kind"]) for d in v4[:156]] == \
        [(d["strategy"], d["timeframe"], d["kind"]) for d in v3]


def test_group_names_are_disjoint_from_the_locked_names():
    from paperbot import sweepsig
    from paperbot.sigservice import strategy_names
    locked = set(strategy_names(sweepsig.lib()))
    assert len(locked) == 36
    ds, flips = set(C.DS200_IDS), set(C.V4_GROUPS["flip"]["names"])
    assert len(ds) == 44 and not ds & locked and not ds & flips
    assert C.REEL_NAME not in locked | ds | flips and not flips & locked
    defs = C.v4_account_defs(sorted(locked))
    assert len({f"{d['strategy']}@{d['timeframe']}" for d in defs}) == 331


def test_ds200_defs_equal_lib_c_and_reel_constants_equal_lib_reel5m():
    """Loaded in a subprocess: lib_c and lib_reel5m change sys.path and the warnings filters at import."""
    code = r"""
import importlib.util, json, sys
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
c = load("lib_c", "research/deepseek200/lib_c.py")
r = load("lib_reel5m", "research/reel5m/lib_reel5m.py")
print(json.dumps({"defs": [[d, f, list(t)] for d, f, t in c.DEFS], "ses": list(c.SESSION_TFS), "tfs": list(c.TFS),
                  "reel": [r.STOP_BUF_ATR, r.MAX_HOLD, r.BB_LEN, r.BB_K, r.MA_LEN, r.WAIT]}))
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert [(d, f, tuple(t)) for d, f, t in got["defs"]] == list(C.DS200_DEFS)
    assert tuple(got["tfs"]) == C.DS200_TFS and tuple(got["ses"]) == C.DS200_SESSION_TFS
    from paperbot import reel_engine as RE
    assert got["reel"][:4] == [RE.STOP_BUF_ATR, RE.MAX_HOLD_5M, RE.BB_LEN, RE.BB_K]


# ------------------------------------------------------------------ settings and leverage
def test_version_is_paper_v4():
    assert C.V4_VERSION == "paper-v4" == S.version == C.v4_settings().version
    assert C.v4_settings is C.v3_settings
    # nothing else of the rule set changed
    assert S.leverage_rule == "quality_v1" and S.tp_mode == "ladder" and S.initial_equity == 5000.0


def test_5m_accounts_are_always_normal():
    from paperbot import levrule as LR
    assert C.V3_P_BEST["5m"] == 0.0
    assert not any(LR.coin_flip_best(k, "5m", sym, 1_790_000_000_000 + i * 300_000)
                   for k in (1, 2, 3) for sym in C.V3_SYMBOLS for i in range(200))
    for strat in ("RANDOM_1", "RANDOM_3", C.REEL_NAME, "F9_FVG"):
        sig = Signal(ts=1_790_000_000_000 - 1, symbol="BTCUSDT", timeframe="5m" if "F9" not in strat else "15m",
                     strategy_id=strat, side=1, stop_price=0.0, tier="best")
        assert LR.signal_group(sig)["group"] == "normal", strat


def test_flip5m_rate_is_the_reels_own():
    f = C.V4_FLIP5M
    assert f["long_only"] is True and f["label"] in ("matched", "unmatched")
    assert f["label"] == "matched" and f["rate"] == round(54_239 / 4_072_373, 6) == 0.013319
    h1 = os.path.join(ROOT, "research", "reel5m", "out", "h1.json")
    if os.path.exists(h1):              # the same run's position-dependent signal count, reproduced when frozen
        assert json.load(open(h1))["skips"]["signals"] == 45_138


def test_windows_and_delay():
    assert C.DS_WINDOW_5M == {"15m": 17_289, "30m": 17_298, "1h": 3_000 * 12, "4h": 2_400 * 48}
    assert C.REEL_WINDOW_5M >= 2_000 and C.FIVE_M_MAX_DELAY_MS == 60_000
    assert C.V4_FLIP_TFS == ("5m", "15m", "30m", "1h", "4h") and C.REEL_TF == "5m"


# ------------------------------------------------------------------ kinds and engines
def test_kinds():
    assert ORIGINAL_KINDS == ("strategy", "random", "ds200", "reel")
    assert {spec["kind"] for spec in C.V4_GROUPS.values()} == set(ORIGINAL_KINDS)
    assert GROUP_OF_KIND == {"strategy": "core", "random": "flip", "ds200": "ds200", "reel": "reel",
                             "copy": "extra", "newlab": "extra"}
    assert hold_others({"kind": "ds200"}) is None and hold_others({"kind": "reel"}) is None
    assert hold_others({"kind": "copy"}) == {"cls": HeldEngine}


def test_exit_rule_of_each_account():
    from paperbot.reel_engine import ReelEngine
    assert exits_of("reel", "5m") == "reel" and original_engine_cls("reel", "5m") is ReelEngine
    v4flip = {"group": "flip", "family": None, "exits": "reel"}
    assert original_engine_cls("random", "5m", v4flip) is ReelEngine
    assert original_engine_cls("random", "5m", json.dumps(v4flip)) is ReelEngine
    # a 5m coin flip of an older run or test world (no such data) keeps the house engine
    assert original_engine_cls("random", "5m") is None and original_engine_cls("random", "5m", "{}") is None
    for kind, tf in (("strategy", "15m"), ("strategy", "5m"), ("ds200", "4h"), ("random", "15m")):
        assert original_engine_cls(kind, tf, {"exits": "reel"}) is None, (kind, tf)
    assert exits_of("random", "5m", "not json") == "house"


def _open_v4(path, notifier=None):
    book = _book(path, notifier)
    book.open_accounts(C.v4_account_defs(CORE), 1_790_000_000_000)
    return book


def test_open_builds_paper_engines_and_reel_engines(tmp_path):
    from paperbot.reel_engine import ReelEngine
    book = _open_v4(tmp_path / "a.db")
    assert len(book.engines) == 331
    reel = {"REEL_H1@5m", "RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m"}
    for aid, e in book.engines.items():
        assert isinstance(e, PaperEngine) and not isinstance(e, HeldEngine)
        assert (type(e) is ReelEngine) == (aid in reel), aid
        if aid not in reel:
            assert type(e) is PaperEngine
    rows = {r["account_id"]: r for r in book.store.accounts()}
    assert json.loads(rows["F9_FVG@1h"]["data"]) == {"group": "ds200", "family": "F9", "exits": "house"}
    assert rows["REEL_H1@5m"]["kind"] == "reel" and rows["REEL_H1@5m"]["settings_version"] == "paper-v4"


@pytest.mark.parametrize("how", ["none", "hold_others", "extras"])
def test_save_load_round_trip_keeps_every_engine(tmp_path, how):
    """After a restart no DeepSeek or reel account becomes a frozen HeldEngine (plan risk 1)."""
    from paperbot.reel_engine import ReelEngine
    db = tmp_path / "r.db"
    book = _open_v4(db)
    book.engines["F1_RSI_DIV@15m"].wallet = 4321.0
    book.engines["REEL_H1@5m"].wallet = 4999.0
    book.save(1_790_000_060_000)
    book.store.close()
    note = ListNotifier()
    store = Store3(str(db))
    if how == "extras":
        from paperbot.live3 import start_extras
        ext, make_of = start_extras(store, note, str(db), S)
        assert ext is not None
        assert make_of({"kind": "ds200", "account_id": "F1_RSI_DIV@15m"}) is None
        assert make_of({"kind": "reel", "account_id": "REEL_H1@5m"}) is None
    else:
        make_of = hold_others if how == "hold_others" else None
    book2 = AccountBook(S, {s: Brackets.example() for s in C.V3_SYMBOLS}, store, note)
    assert book2.load(make_of=make_of)
    assert len(book2.engines) == 331
    assert not [a for a, e in book2.engines.items() if isinstance(e, HeldEngine)]
    assert type(book2.engines["F1_RSI_DIV@15m"]) is PaperEngine and book2.engines["F1_RSI_DIV@15m"].wallet == 4321.0
    assert type(book2.engines["REEL_H1@5m"]) is ReelEngine and book2.engines["REEL_H1@5m"].wallet == 4999.0
    assert type(book2.engines["RANDOM_2@5m"]) is ReelEngine and type(book2.engines["RANDOM_2@15m"]) is PaperEngine
    assert {a: m["kind"] for a, m in book2.meta.items()}["F15_ORB@4h"] == "ds200"
    assert not [m for m in note.messages if m[0] == "CRITICAL"]


def test_broken_reel_engine_holds_only_the_reel_accounts(tmp_path, monkeypatch):
    db = tmp_path / "h.db"
    book = _open_v4(db)
    book.save(1_790_000_060_000)
    book.store.close()
    monkeypatch.setitem(sys.modules, "paperbot.reel_engine", None)        # import paperbot.reel_engine raises
    note = ListNotifier()
    book2 = AccountBook(S, {s: Brackets.example() for s in C.V3_SYMBOLS}, Store3(str(db)), note)
    assert book2.load()
    held = sorted(a for a, e in book2.engines.items() if isinstance(e, HeldEngine))
    assert held == ["RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m", "REEL_H1@5m"]
    assert all(type(e) is PaperEngine for a, e in book2.engines.items() if a not in held)
    crit = [t for lvl, t in note.messages if lvl == "CRITICAL"]
    assert len(crit) == 4 and all("engine code failed to load" in t for t in crit)


def test_v3_world_unchanged(tmp_path):
    """A v3-shaped book (no data on its rows, a 5m coin flip of an older world included) builds exactly the engines
    it built before v4: PaperEngine for every original account."""
    from paperbot.live3 import account_defs
    book = _book(tmp_path / "v3.db")
    book.open_accounts(account_defs(["A", "B"], ("5m", "15m")), 0)
    assert all(type(e) is PaperEngine for e in book.engines.values()) and "RANDOM_1@5m" in book.engines
    book.save(0)
    book.store.close()
    book2 = _book(tmp_path / "v3.db")
    assert book2.load(make_of=hold_others)
    assert all(type(e) is PaperEngine for e in book2.engines.values())


# ------------------------------------------------------------------ interfaces of the new modules (P2, P3, P5)
def test_dssig_interface():
    from paperbot import dssig
    assert issubclass(dssig.DsUnavailable, dssig.DsError) and issubclass(dssig.DsError, Exception)
    assert [len(dssig.defs_for(tf)) for tf in ("15m", "30m", "1h", "4h")] == [44, 44, 44, 39]
    assert dssig.defs_for("5m") == [] and dssig.defs_for("1d") == []
    assert not set(SESSION_DEFS) & set(dssig.defs_for("4h"))
    assert dssig.defs_for("15m") == list(C.DS200_IDS)
    assert list(inspect.signature(dssig.verify).parameters) == []
    assert list(inspect.signature(dssig.ds_job).parameters) == ["args"]


def test_reelsig_and_reel_engine_interface():
    from paperbot import reel_engine as RE
    from paperbot import reelsig
    assert issubclass(reelsig.ReelUnavailable, reelsig.ReelError)
    assert list(inspect.signature(reelsig.signal).parameters) == ["df5m_closed"]
    assert list(inspect.signature(reelsig.flip_levels).parameters) == ["df5m_closed"]
    assert list(inspect.signature(reelsig.verify).parameters) == []
    assert issubclass(RE.ReelEngine, PaperEngine)
    assert list(inspect.signature(RE.simulate_exit).parameters) == ["bars5m", "entry_idx", "entry_price", "stop",
                                                                   "side"]
    assert inspect.signature(RE.simulate_exit).parameters["side"].default == 1
    assert RE.FLIP_LOOKBACK == 12
