"""research/hunt/reads_o.py: the Phase-B autopsy reads O1-O5 of the trend hunt (PREREG_HUNT_WIDE W 7.4a). Synthetic
values and synthetic coins only; no real price is read.

- pure functions: weekend and blackout masks (boundaries), the longs-only variant, ET -> UTC with US daylight saving,
  the macro calendar's schema and counts (the repository file included), momentum sides (zero move, too few bars),
  D11 redaction
- gates: O2 runs only with a pinned, sound, verified calendar; run(ctx) and the standalone runner refuse without the
  module's own pin line
- engine: run(ctx) end to end through hunt.reads_context on synthetic coins (controls filtered by the same rule,
  D11 check of the hook, determinism); the select-only map uses no bar at or after the select end
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import types

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt import reads_o as RO  # noqa: E402

DAY = H.DAY_MS
FIVE = H.FIVE
HOUR = 3_600_000


def utc(s: str) -> int:
    """'YYYY-MM-DD HH:MM' UTC -> ms."""
    return H._parse_utc(s)


# ------------------------------------------------------------------ O1 weekend boundaries
def test_weekend_filter_boundaries():
    # 2024-03-08 is a Friday, 03-09 Saturday, 03-10 Sunday, 03-11 Monday
    closes = [utc("2024-03-08 23:55"), utc("2024-03-09 00:00"), utc("2024-03-10 23:55"), utc("2024-03-11 00:00"),
              utc("2024-03-09 12:00"), utc("2024-03-11 00:05"), utc("2024-03-08 00:00")]
    assert RO.is_weekend_close(closes).tolist() == [False, True, True, False, True, False, False]
    assert RO.utc_weekday([utc("1970-01-01 00:00"), utc("2024-03-11 00:00")]).tolist() == [3, 0]


def test_weekend_boundaries_on_every_timeframe_close():
    """4h, 1h, 30m and 15m bars closing at Sat 00:00 are weekend bars; the ones closing at Mon 00:00 are not."""
    for tf, ms in H.TF_MS.items():
        sat, mon = utc("2024-03-09 00:00"), utc("2024-03-11 00:00")
        closes = np.asarray([sat - ms, sat, mon - ms, mon])
        assert RO.is_weekend_close(closes).tolist() == [False, True, True, False], tf


def test_longs_only_variant():
    c = np.asarray([utc("2024-03-09 04:00")] * 2 + [utc("2024-03-08 20:00")] * 2)
    side = np.asarray([1, -1, 1, -1])
    assert RO.skip_mask("O1", c, side).tolist() == [True, True, False, False]
    assert RO.skip_mask("O1b", c, side).tolist() == [True, False, False, False]
    assert RO.skip_mask("base", c, side).tolist() == [False] * 4
    with pytest.raises(ValueError):
        RO.skip_mask("O2", c, side, None)


# ------------------------------------------------------------------ O2 blackout edges
def test_blackout_window_edges():
    T = utc("2024-03-20 18:00")
    closes = [T - 125 * 60_000, T - 120 * 60_000, T - 60 * 60_000, T, T + 5 * 60_000, T + 15 * 60_000]
    assert RO.in_blackout(closes, [T]).tolist() == [False, True, True, True, False, False]
    # two events: the nearer next event decides; an empty event list blacks out nothing
    T2 = T + 3 * HOUR
    assert RO.in_blackout([T + HOUR, T2 - HOUR, T2 + 1], [T2, T]).tolist() == [True, True, False]
    assert RO.in_blackout([T], []).tolist() == [False]
    ev = {"fomc": np.asarray([T]), "nfp": np.asarray([T2])}
    assert RO.skip_mask("O2_fomc", [T, T2], [1, 1], ev).tolist() == [True, False]
    assert RO.skip_mask("O2", [T, T2], [1, -1], ev).tolist() == [True, True]


# ------------------------------------------------------------------ ET -> UTC and the calendar
@pytest.mark.parametrize("date,time_,want", [
    ("2024-03-08", "08:30", "2024-03-08T13:30Z"),      # NFP, EST (DST starts 2024-03-10)
    ("2024-03-20", "14:00", "2024-03-20T18:00Z"),      # FOMC, EDT
    ("2024-11-01", "08:30", "2024-11-01T12:30Z"),      # NFP, EDT (DST ends 2024-11-03)
    ("2024-11-07", "14:00", "2024-11-07T19:00Z"),      # FOMC, EST
    ("2024-03-10", "08:30", "2024-03-10T12:30Z"),      # DST start Sunday after 02:00
    ("2024-11-03", "08:30", "2024-11-03T13:30Z"),      # DST end Sunday after 02:00
    ("2020-03-15", "17:00", "2020-03-15T21:00Z"),      # the Sunday unscheduled meeting (DST from 2020-03-08)
    ("2025-03-07", "08:30", "2025-03-07T13:30Z"),      # DST starts 2025-03-09
    ("2023-11-03", "08:30", "2023-11-03T12:30Z"),      # DST ends 2023-11-05
])
def test_et_to_utc_with_daylight_saving(date, time_, want):
    assert RO.utc_iso(RO.et_to_utc_ms(date, time_)) == want


def test_et_to_utc_matches_zoneinfo_every_day():
    zoneinfo = pytest.importorskip("zoneinfo")
    import datetime as dt
    z = zoneinfo.ZoneInfo("America/New_York")
    d = dt.date(2020, 1, 1)
    while d < dt.date(2027, 1, 1):
        for hh, mm in ((8, 30), (14, 0)):
            ref = int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=z).timestamp() * 1000)
            assert RO.et_to_utc_ms(d.isoformat(), f"{hh:02d}:{mm:02d}") == ref, d
        d += dt.timedelta(days=1)


def _cal_doc():
    with open(os.path.join(ROOT, RO.CALENDAR_REL)) as fh:
        return json.load(fh)


def test_repository_calendar_schema_and_counts():
    doc = _cal_doc()
    assert RO.validate_calendar(doc) == []
    c = doc["counts"]
    for y in range(2021, 2027):
        sched = [e for e in doc["events"] if e["kind"] == "FOMC" and e["date_et"].startswith(str(y))
                 and e["meeting_type"] == "scheduled"]
        assert len(sched) == 8, y
        assert all(e["time_et"] == "14:00" for e in sched)
    for y in (2020, 2021, 2022, 2023, 2024, 2026):
        assert c["NFP"][str(y)] == 12, y
    assert c["NFP"]["2025"] == 11 and "NFP:2025" in doc["count_exceptions"]
    assert c["FOMC"]["2020"] == 10 and "FOMC:2020" in doc["count_exceptions"]
    nfp = [e for e in doc["events"] if e["kind"] == "NFP"]
    assert all(e["time_et"] == "08:30" for e in nfp)
    assert all(e["source_urls"][0].startswith("https://www.bls.gov/") for e in nfp)
    # the rescheduled releases are on their actual dates
    dates = {e["date_et"] for e in nfp}
    assert {"2025-11-20", "2025-12-16", "2026-02-11"} <= dates and not {"2025-10-03", "2026-02-06"} & dates
    # every NFP event names its reference month as YYYY-MM; the 2025-12-16 release is the November report
    assert all(len(e["reference_month"]) == 7 for e in nfp)
    assert next(e for e in nfp if e["date_et"] == "2025-12-16")["reference_month"] == "2025-11"
    # the dates not used as a T are listed with a reason: 2020 notation votes without a policy statement, the
    # longer-run-goals votes, the shutdown's original NFP dates
    exc = {(x["kind"], x["date_et"]) for x in doc["excluded"]}
    assert {("FOMC", "2020-03-18"), ("FOMC", "2020-03-19"), ("FOMC", "2020-03-31"), ("FOMC", "2020-08-27"),
            ("FOMC", "2025-08-22"), ("NFP", "2025-10-03"), ("NFP", "2025-11-07"), ("NFP", "2025-12-05"),
            ("NFP", "2026-02-06")} <= exc
    fomc2020 = [e for e in doc["events"] if e["kind"] == "FOMC" and e["date_et"].startswith("2020")]
    assert [e["meeting_type"] for e in fomc2020].count("notation_vote") == 1        # only March 23's statement
    # honest status: nothing was fetched, so nothing is marked verified, and the read would not run on it
    assert not any(e["verified_official"] for e in doc["events"])
    assert "UNVERIFIED" in doc["status"]


def test_calendar_schema_catches_errors():
    doc = _cal_doc()
    bad = copy.deepcopy(doc)
    bad["events"][3]["t_ms"] += HOUR                              # a wrong UTC conversion
    assert any("t_ms" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    e = next(x for x in bad["events"] if x["kind"] == "NFP" and x["date_et"] == "2024-03-08")
    e["tz"] = "EDT"                                               # the day before daylight saving starts
    assert any("tz" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    bad["events"] = [x for x in bad["events"] if x["date_et"] != "2023-06-02"]
    bad["counts"] = RO.calendar_counts(bad["events"])
    assert any("NFP 2023: 11 releases" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    bad["events"][0]["source_urls"] = ["https://example.com/fomc"]
    assert any("official" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    bad["counts"]["FOMC"]["2024"] = 9
    assert any("counts in the file" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    bad["events"][5], bad["events"][6] = bad["events"][6], bad["events"][5]
    assert any("time order" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    next(x for x in bad["events"] if x["kind"] == "NFP")["reference_month"] = "2019-12 (note)"
    assert any("reference_month" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    bad["excluded"].append({"kind": "NFP", "date_et": "2024-03-08", "why": "listed twice"})
    assert any("also an event" in p for p in RO.validate_calendar(bad))
    bad = copy.deepcopy(doc)
    bad["excluded"].append({"kind": "FOMC", "date_et": "2024-01-01"})
    assert any("needs kind, date_et and why" in p for p in RO.validate_calendar(bad))


def _cal_tree(tmp_path, monkeypatch, verified: bool, pinned: bool):
    """The repository calendar copied to a temporary pin tree (verified flags set as asked)."""
    doc = _cal_doc()
    for e in doc["events"]:
        e["verified_official"] = verified
    cal = tmp_path / "macro_calendar.json"
    cal.write_text(json.dumps(doc))
    pin = tmp_path / "PIN.sha256"
    pin.write_text((f"{H.sha256_file(str(cal))}  {cal}\n" if pinned else "") + f"{'0' * 64}  other/file\n")
    monkeypatch.setattr(RO, "CALENDAR_REL", str(cal))
    monkeypatch.setattr(H, "PIN", {"wide": str(pin), "v1": str(pin)})
    return cal, pin


def test_calendar_gate(tmp_path, monkeypatch):
    per = {"select": (H.day_ms("2021-01-01"), H.day_ms("2024-01-01")),
           "test": (H.day_ms("2024-01-01"), H.day_ms("2026-10-01"))}
    _cal_tree(tmp_path, monkeypatch, verified=True, pinned=False)
    st = RO.calendar_status("wide", per)
    assert not st["run"] and "not in" in st["reason"]
    cal, _ = _cal_tree(tmp_path, monkeypatch, verified=False, pinned=True)
    st = RO.calendar_status("wide", per)
    assert st["pinned"] and not st["run"] and st["unverified_in_periods"] > 100
    cal, _ = _cal_tree(tmp_path, monkeypatch, verified=True, pinned=True)
    st = RO.calendar_status("wide", per)
    assert st["run"] and len(st["events"]["fomc"]) == 58 and len(st["events"]["nfp"]) == 83
    assert st["counts_in_periods"]["FOMC"] == 46                  # 2021-01 .. 2026-09: 8 x 5 + 6
    cal.write_text(cal.read_text().replace('"14:00"', '"14:30"', 1))   # changed after the pin line
    assert not RO.calendar_status("wide", per)["run"]


# ------------------------------------------------------------------ O4 momentum side
def test_momentum_side_rule():
    c = np.arange(30, dtype=float) + 100.0
    c[25] = c[5]                                                    # zero move at j = 25
    c[26] = c[6] - 1.0                                              # down move at j = 26
    side, ok = RO.momentum_from_closes(c, [3, 19, 20, 24, 25, 26])
    assert ok.tolist() == [False, False, True, True, True, True]
    assert side.tolist() == [0, 0, 1, 1, 0, -1]


# ------------------------------------------------------------------ base positions removed (distinct, side-matched)
def test_removed_base_positions_distinct_and_side_matched():
    t = utc("2024-03-09 00:05")
    taken = {(0, t, 1), (1, t, -1)}                                  # base positions: coin, fill, side
    # two skipped signals (two basket members, 1h and 4h, both closing Sat 00:00) share one base position
    coin, fill, side = [0, 0, 1, 1], [t, t, t, t], [1, 1, 1, -1]
    assert RO.removed_base_positions(taken, coin, fill, side, [True, True, False, False]) == 1
    # O1b: a skipped long does not match the base short at the same coin and fill
    assert RO.removed_base_positions(taken, coin, fill, side, [False, False, True, False]) == 0
    assert RO.removed_base_positions(taken, coin, fill, side, [True, True, True, True]) == 2
    assert RO.removed_base_positions(set(), coin, fill, side, [True] * 4) == 0
    assert RO.removed_base_positions(taken, [], [], [], []) == 0


# ------------------------------------------------------------------ O3 plan (not computed; no edit of hunt.py)
def test_o3_plan_is_a_separate_pinned_module_and_halves_every_cells_cap():
    from research.hunt import reads_a as RA
    txt = " ".join(RO.O3_NEEDS)
    assert "research/hunt/reads_o3.py" in txt and "never an edit of hunt.py" in txt
    assert "bit-identical" in txt and "PR_SIDECAP" not in txt and "SKIP_NAMES +=" not in txt
    for cell in RA.board_cells():                                     # half of the cell's total open-risk cap
        r, ov = RA.cell_overrides(*cell)
        assert f"{r * 100:g}%: {ov['PR_CAP'] / 2 * 100:g}%" in txt, cell


# ------------------------------------------------------------------ D11 redaction
def test_redact_keeps_labels_and_counts_only():
    obj = {"row": "pick:F3:X:1h:G1", "mean_lnM": 0.1, "n_positions": np.int64(4), "bust": np.bool_(False),
           "labels": ["a"], "periods": {"test": {"O1": {"signals": {"gated": 3}, "max_dd": np.float32(0.2),
                                                         "ci": [0.1, 0.4], "cell": "B|5%"}}}}
    r = RO.redact(obj)
    assert r == {"row": "pick:F3:X:1h:G1", "n_positions": 4, "bust": False, "labels": ["a"],
                 "periods": {"test": {"O1": {"signals": {"gated": 3}, "ci": [], "cell": "B|5%"}}}}
    pub, priv = RO.split_ds({"pick:F3:X:1h:G1": obj, "pick:F2:Y:1h:G1": {"mean_lnM": 0.2}}, {"pick:F3:X:1h:G1": True})
    assert pub["pick:F3:X:1h:G1"]["note"] == RO.DS_NOTE and priv["pick:F3:X:1h:G1"]["mean_lnM"] == 0.1
    assert pub["pick:F2:Y:1h:G1"]["mean_lnM"] == 0.2 and "pick:F2:Y:1h:G1" not in priv
    assert H.d11_problems(pub, {"F3:X:1h:G1"}) == []


# ------------------------------------------------------------------ refusal without the module's own pin line
def test_runner_refuses_when_not_pinned(tmp_path, monkeypatch, capsys):
    (tmp_path / "research" / "hunt").mkdir(parents=True)
    mod = tmp_path / RO.MODULE_REL
    shutil.copy(os.path.join(ROOT, RO.MODULE_REL), mod)
    pin = tmp_path / H.PIN["wide"]
    pin.write_text(f"{'0' * 64}  research/hunt/hunt.py\n")
    monkeypatch.setattr(H, "ROOT", str(tmp_path))
    assert "not in research/hunt/PREREG_HUNT_WIDE.sha256" in RO.pin_refusal("wide")
    assert RO.main(["--study", "wide", "--data", str(tmp_path)]) == 2      # before any data or test.json is read
    assert "refused" in capsys.readouterr().err
    with open(pin, "a") as fh:                                    # a stale line (another sha256) still refuses
        fh.write(f"{'1' * 64}  {RO.MODULE_REL}\n")
    assert RO.pin_refusal("wide") is not None
    with open(pin, "a") as fh:
        fh.write(f"{H.sha256_file(str(mod))}  {RO.MODULE_REL}\n")
    assert RO.pin_refusal("wide") is None
    assert H.reads_pin_status("wide", "reads_o", None)["listed_in_pin"]
    mod.write_text(mod.read_text() + "\n# edited\n")              # edited after the pin line
    assert RO.pin_refusal("wide") is not None
    assert "reads_o" not in H.READS_MODULES                       # hunt.py is pinned and unchanged


def test_run_refuses_without_its_pin_line():
    for rp in (None, {"listed_before_test_json": True}, {"module": "research/hunt/reads_a.py", "listed_in_pin": True},
               {"module": RO.MODULE_REL, "listed_in_pin": False}):
        with pytest.raises(RuntimeError, match="pinned line"):
            RO.run({"reads_pin": rp})


# ------------------------------------------------------------------ engine on synthetic coins
S0 = H.day_ms("2023-05-01")
EXTRA = (H.day_ms("2023-12-01"), H.day_ms("2024-01-01"))
SELECT = (H.day_ms("2024-01-01"), H.day_ms("2024-02-01"))
TEST = (H.day_ms("2024-02-01"), H.day_ms("2024-03-02"))
SYMS = ["BTCUSDT", "ETHUSDT", "AAAUSDT"]


def _events(spec, sym, ser, btc):
    """Deterministic synthetic events (replaces entries_wide in these tests)."""
    n = len(ser.bars.close_ms)
    i = np.arange(n)
    off = (sum(map(ord, sym)) + sum(map(ord, spec["name"]))) % 13
    return (i % 29 == off), (i % 31 == (off + 7) % 31)


def _events_lookahead(spec, sym, ser, btc):
    """Non-causal synthetic events: a bar fires when its close is above the median close of the WHOLE loaded series,
    so any later bar the code can see changes the select-period events."""
    c = np.asarray(ser.bars.c)
    i = np.arange(len(c))
    up = c > np.median(c)
    return up & (i % 17 == 3), ~up & (i % 19 == 5)


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    coins = {s: H.synth_coin(s, S0, TEST[1], 500 + i, 50.0 * (i + 1)) for i, s in enumerate(SYMS)}
    fund = {s: H.synth_funding(S0, TEST[1], 900 + i) for i, s in enumerate(SYMS)}
    H.install(coins, fund)
    orig = H.entry_events
    H.entry_events = _events
    mks = {"extra": H.Market(SYMS, EXTRA, name="extra"), "select": H.Market(SYMS, SELECT, name="select"),
           "test": H.Market(SYMS, TEST, name="test")}
    for m in mks.values():
        H._G["mk"][m.key] = m
    yield {"mks": mks, "tmp": tmp_path_factory.mktemp("reads_o"), "coins": coins, "fund": fund}
    H.entry_events = orig


def _spec(i, name, kind, family, tf="1h", gate="NONE"):
    return {"id": f"{family}:{name}:{tf}:{gate}", "family": family, "name": name, "strategy": name, "kind": kind,
            "tf": tf, "gate": gate, "combo": {}, "pick_no": i, "batch": 1, "rank": None}


MAP_SYSTEMS = [_spec(0, "AAA", "core", "F2"), _spec(0, "AAA", "core", "F2", "4h"), _spec(0, "BBB", "core", "F2"),
               _spec(0, "DSX", "ds", "F3", "30m"), _spec(0, "TURTLE20", "famous", "F5", "15m")]


def _ctx(synth, monkeypatch, picks=None):
    mks = synth["mks"]
    picks = picks or [_spec(1, "AAA", "core", "F2"), _spec(2, "DSX", "ds", "F3", "30m"),
                      _spec(3, "N17_KC_RSI", "core", "F2", "4h")]
    test_doc = {"picks": picks, "verdict": {"passing": [], "label": "picks", "wide_pass": False},
                "results": {p["id"]: {} for p in picks}, "lineup": {}, "untested": ["F2:BBB:1h:NONE"]}
    args = types.SimpleNamespace(procs=1, private=str(synth["tmp"]), data=str(synth["tmp"]))
    rp = {"module": RO.MODULE_REL, "sha256": "x", "listed_in_pin": True, "listed_before_test_json": False}
    ctx = H.reads_context("wide", args=args, pin=None, mks=mks, syms=SYMS, test_doc=test_doc, full=None,
                          reads_pin=rp, private_path=str(synth["tmp"] / "p.json"))
    ctx["rows"] = [r for r in ctx["rows"] if r["kind"] != "v1"]
    ctx["periods"] = {"extra": list(EXTRA), "select": list(SELECT), "test": list(TEST)}
    ctx["log"] = lambda m: None
    for k, v in (("CTL_SEEDS", 3), ("CTL_TASK_SEEDS", 2), ("E_SEEDS", {"test": 4, "select": 3}),
                 ("E_TASK_SEEDS", 3)):
        monkeypatch.setattr(RO, k, v)
    monkeypatch.setattr(RO, "map_systems", lambda live: [dict(s) for s in MAP_SYSTEMS])
    monkeypatch.setattr(RO, "_select_paths", lambda c: (str(synth["tmp"] / "absent_select.json"), None))
    return ctx


def _verified_calendar(tmp_path, monkeypatch):
    return _cal_tree(tmp_path, monkeypatch, verified=True, pinned=True)


def test_run_end_to_end_on_synthetic_coins(synth, monkeypatch, tmp_path):
    _verified_calendar(tmp_path, monkeypatch)
    ctx = _ctx(synth, monkeypatch)
    seen = []
    run0 = ctx["run"]

    def spy(what, a, b, **kw):                                    # every run's signals, for the filter checks
        seen.append((what, kw.get("start_wallet", H.START_WALLET)))
        return run0(what, a, b, **kw)
    ctx["run"] = spy
    RO.run(ctx)
    out, priv = ctx["out"], ctx["private"]
    rows = {r["row"]: r for r in ctx["rows"]}
    assert set(rows) == {"pick:F2:AAA:1h:NONE", "pick:F3:DSX:30m:NONE", "pick:F2:N17_KC_RSI:4h:NONE",
                         "basket_batch1"}
    ds_ids = {"F3:DSX:30m:NONE", "pick:F3:DSX:30m:NONE", "basket_batch1"}
    assert H.d11_problems(out, ds_ids) == []                      # the hook's own D11 check
    assert out["calendar"]["run"] is True and out["constants"]["variants"] == list(RO.VARIANTS)
    g = out["rows"]["pick:F2:AAA:1h:NONE"]
    for p in ("select", "test"):
        base, o1, o1b = (g["periods"][p][v] for v in ("base", "O1", "O1b"))
        assert base["signals"]["skipped"] == 0 and o1["signals"]["skipped"] > 0
        assert o1["signals"]["skipped"] == o1["signals"]["skipped_long"] + o1["signals"]["skipped_short"]
        assert o1b["signals"]["skipped"] == o1["signals"]["skipped_long"] and o1b["signals"]["skipped_short"] == 0
        assert o1["signals"]["gated"] == base["signals"]["gated"] == base["signals"]["kept"]
        for v in RO.VARIANTS:
            s = g["periods"][p][v]
            assert set(s["controls"]) == {"a", "b"} and s["controls"]["a"]["n_seeds"] == 3
            assert s["mean_lnM"] is not None and s["cost2_mean_lnM"] is not None and "win_share" in s
            h = s["headline_at_size_fixed_on_select"]
            if g["size_fixed_on_select"]:
                assert h["cell"] == g["size_fixed_on_select"] and h["n_windows"] == 1
                assert set(h["shares"]) == set(RO.HEAD_COLS) and h["controls"]["b"]["n_seeds"] == 3
            if v != "base":
                assert set(s["minus_base"]) >= {"mean_lnM", "mean_d_a", "mean_d_b", "n_positions"}
                assert 0 <= s["base_positions_removed"] <= s["signals"]["skipped"]
                assert s["base_positions_removed"] <= base["n_positions"]
        o4 = g["periods"][p]["O4"]
        assert o4["e"]["n_seeds"] == RO.E_SEEDS[p] and 0.0 < o4["e"]["seed_rank_p"] <= 1.0
        assert o4["f"]["signals"] == base["signals"]["gated"]
        assert o4["f"]["same_side"] <= o4["f"]["signals"]
    assert g["periods"]["test"]["O2"]["signals"]["skipped"] >= g["periods"]["test"]["O2_fomc"]["signals"]["skipped"]
    assert isinstance(g["momentum_only"], bool)
    # the side-matched count finds the base positions the weekend rule removes (trade sides are +1 / -1 like signals)
    assert sum(g["periods"][p]["O1"]["base_positions_removed"] for p in ("select", "test")) > 0
    # by timeframe: all four timeframes in every variant and period, a note where no public row exists
    for v in ("O1", "O1b", "O2", "O2_fomc"):
        for p in ("select", "test"):
            bt = out["by_timeframe"][v][p]
            assert list(bt) == list(H.TF_ORDER)
            assert bt["1h"]["rows"] == 1 and bt["4h"]["rows"] == 1
            assert bt["15m"] == {"rows": 0, "note": RO.TF_NOTE_NONE}
            assert bt["30m"] == {"rows": 0, "note": RO.TF_NOTE_DS_ONLY}          # the DeepSeek pick only
            assert priv["by_timeframe_all_rows"][v][p]["30m"]["rows"] == 1
    # some runs (base, size fix) saw weekend signals; the per-variant filter of every run is checked in
    # test_controls_filtered_the_same_way
    assert sum(int(RO.is_weekend_close(RO.close_ms_of(H, SYMS, sig)).sum())
               for what, _ in seen for sig, _src in what if len(sig["k"])) > 0
    # D11: the DeepSeek row and the basket that holds it keep labels and counts; figures in private
    pd = out["rows"]["pick:F3:DSX:30m:NONE"]
    assert pd["note"] == RO.DS_NOTE and "mean_lnM" not in pd["periods"]["test"]["O1"]
    assert pd["periods"]["test"]["O1"]["signals"]["gated"] >= 0
    assert priv["rows"]["pick:F3:DSX:30m:NONE"]["periods"]["test"]["O1"]["mean_lnM"] is not None
    assert out["rows"]["basket_batch1"]["note"] == RO.DS_NOTE and "basket_batch1" in priv["rows"]
    # O5, O3, labels
    assert out["rows"]["pick:F2:N17_KC_RSI:4h:NONE"]["labels"][-1] == RO.O5_LABEL
    assert out["O5"]["rows"] == ["pick:F2:N17_KC_RSI:4h:NONE"]
    assert out["O3"]["needs"] and "not computed" in out["O3"]["status"]
    # the select-only map: weekend-skip walk on select, never run on test, DeepSeek map rows redacted
    mp = out["O1_select_map"]
    assert mp["run_on_test"] is False and mp["n_systems"] == len(MAP_SYSTEMS)
    assert mp["last_5m_bar_used"] < H.ms_str(SELECT[1])
    assert mp["rows"]["F3:DSX:30m:NONE"]["note"] == RO.DS_NOTE and "score" not in mp["rows"]["F3:DSX:30m:NONE"]
    assert "score" in mp["rows"]["F2:AAA:1h:NONE"] and priv["O1_select_map"]["rows"]["F3:DSX:30m:NONE"]["score"]
    assert set(mp["in_both"]) | set(mp["map_only"]) == set(mp["picks"])
    assert mp["official_members"][-1] == "F2:BBB:1h:NONE"         # untested batch members count as official members
    assert list(mp["by_timeframe"]) == list(H.TF_ORDER)            # no select.json here: counts, no weekends column
    assert mp["by_timeframe"]["1h"]["systems"] == 2 and mp["by_timeframe"]["1h"]["eligible_with_weekends"] is None
    assert "select.json not found" in mp["select_table"]["note"] and mp["select_json_check"]["n"] == 0
    json.dumps(out)
    json.dumps(priv)
    # determinism: a second run gives the same figures
    ctx2 = _ctx(synth, monkeypatch)
    RO.run(ctx2)
    strip = lambda d: {k: v for k, v in d.items() if k != "seconds"}  # noqa: E731
    o1, o2 = strip(out), strip(ctx2["out"])
    o1["O1_select_map"], o2["O1_select_map"] = strip(o1["O1_select_map"]), strip(o2["O1_select_map"])
    assert repr(o1) == repr(o2)


def test_controls_filtered_the_same_way(synth, monkeypatch):
    """Every control run of an O1 / O1b variant holds no weekend first-unit signal (O1b: no weekend long), while the
    same seeds' base runs do: _ctl_task filters each pinned draw by its own signal-bar close and side."""
    ctx = _ctx(synth, monkeypatch)
    seen = []
    run0 = ctx["run"]

    def spy(what, a, b, **kw):
        seen.append(what)
        return run0(what, a, b, **kw)
    ctx["run"] = spy
    rows = ctx["rows"]
    periods = {p: (int(ctx["periods"][p][0]), int(ctx["periods"][p][1])) for p in RO.O_PERIODS}
    RO._S.clear()
    RO._S.update(ctx=ctx, live=H, syms=SYMS, periods=periods, variants=["base", "O1", "O1b"], events=None,
                 wins={p: [] for p in RO.O_PERIODS}, fixed={0: None})
    out = RO._ctl_task((0, "test", "a", (1, 2)))
    assert set(out[4]) == {"base", "O1", "O1b"} and out[4]["O1"].shape[0] == 2
    assert len(seen) == 2 * 3                                     # 2 seeds x 3 variants, base first
    for i, what in enumerate(seen):
        v = ("base", "O1", "O1b")[i % 3]
        sig = what[0][0]
        wk = RO.is_weekend_close(RO.close_ms_of(H, SYMS, sig))
        if v == "base":
            assert wk.any()
        elif v == "O1":
            assert not wk.any()
        else:
            assert not (wk & (np.asarray(sig["side"]) > 0)).any() and (wk & (np.asarray(sig["side"]) < 0)).any()
    # the draws are the pinned W 6 draws: the base run's signals equal control_signals' for that seed
    d1 = ctx["control_signals"](rows[0]["members"][0], "a", "test", H.R_BASE, 1)
    assert np.array_equal(seen[0][0][0]["j"], d1["j"]) and np.array_equal(seen[0][0][0]["side"], d1["side"])


def test_select_map_never_touches_test_bars(synth, monkeypatch):
    """The map cuts every coin at the select end before anything uses it: with non-causal synthetic events, test-
    period bars changed beyond recognition leave the map unchanged, although the same events on the full loaded
    series differ. The process state is restored after the map."""
    ctx = _ctx(synth, monkeypatch)
    monkeypatch.setattr(H, "entry_events", _events_lookahead)
    before = {s: H._COINS[s] for s in SYMS}
    ser_before = dict(H._SERIES)
    pub1, priv1 = RO.select_weekend_map(ctx, H, ["F2:AAA:1h:NONE"])
    assert {s: H._COINS[s] for s in SYMS} == before and dict(H._SERIES) == ser_before
    snap = RO._snapshot(H)
    try:
        poisoned = {}
        for s, c in synth["coins"].items():
            k = int(np.searchsorted(c.ts, SELECT[1], "left"))
            f = lambda x: np.r_[x[:k], x[k:] * 7.0]  # noqa: E731
            poisoned[s] = H.Coin(s, c.ts, f(c.o), f(c.h), f(c.l), f(c.c), c.v, c.qv)
        H.install(poisoned, synth["fund"])
        pub2, priv2 = RO.select_weekend_map(ctx, H, ["F2:AAA:1h:NONE"])
        # teeth: on the full loaded (poisoned) series the same events differ in the select period
        spec = MAP_SYSTEMS[0]
        mk_full = H.Market(SYMS, SELECT, name="full")
        poisoned_sig = H.system_signals(mk_full, spec)
    finally:
        RO._restore(H, snap)
    H._EVENTS.clear()
    H._SIGS.clear()
    clean_sig = H.system_signals(H.Market(SYMS, SELECT, name="full2"), MAP_SYSTEMS[0])
    assert not np.array_equal(poisoned_sig["j"], clean_sig["j"])
    strip = lambda d: {k: v for k, v in d.items() if k != "seconds"}  # noqa: E731
    assert repr(strip(priv1)) == repr(strip(priv2))
    assert priv1["last_5m_bar_used"] == H.ms_str(SELECT[1] - FIVE)
    H._EVENTS.clear()
    H._SIGS.clear()


def test_select_map_equals_the_select_step_on_cut_data(synth, monkeypatch):
    """The map's rows are the select step's computation (data loaded only to the select end, Market(syms, period),
    system_signals, run_signals at base cost and cost x2, wide_eligible) with the weekend rule applied."""
    ctx = _ctx(synth, monkeypatch)
    _, priv = RO.select_weekend_map(ctx, H, [])
    snap = RO._snapshot(H)
    try:
        cut = {}
        for s, c in synth["coins"].items():
            k = int(np.searchsorted(c.ts, SELECT[1], "left"))
            cut[s] = H.Coin(s, c.ts[:k].copy(), c.o[:k].copy(), c.h[:k].copy(), c.l[:k].copy(), c.c[:k].copy(),
                            c.v[:k].copy(), c.qv[:k].copy())
        fund = {s: (ts[ts < SELECT[1]], r[ts < SELECT[1]]) for s, (ts, r) in synth["fund"].items()}
        H.install(cut, fund)
        mk = H.Market(SYMS, SELECT, name="select")
        for spec in MAP_SYSTEMS:
            sig = H.system_signals(mk, spec)
            close = RO.close_ms_of(H, SYMS, sig)
            keep = ~RO.is_weekend_close(close)
            f = {"tf": sig["tf"], "k": sig["k"][keep], "j": sig["j"][keep], "side": sig["side"][keep]}
            base = H.run_signals(mk, [(f, 0)], H.R_BASE, "base")
            c2 = H.run_signals(mk, [(f, 0)], H.R_BASE, "x2")
            row = priv["rows"][spec["id"]]
            assert row["score"] == base["mean_lnM"] and row["cost2_mean_lnM"] == c2["mean_lnM"]
            assert row["n_positions"] == base["n_positions"] and row["eligible"] == H.wide_eligible(base, c2)[0]
            assert row["weekend_skipped"] == int((~keep).sum()) and row["gated"] == len(sig["k"])
    finally:
        RO._restore(H, snap)
    H._EVENTS.clear()
    H._SIGS.clear()


def _select_rows_on_cut(synth, weekends: bool) -> list:
    """The select step's rows for MAP_SYSTEMS on data cut at the select end (weekends included unless asked)."""
    snap = RO._snapshot(H)
    rows = []
    try:
        cut = {}
        for s, c in synth["coins"].items():
            k = int(np.searchsorted(c.ts, SELECT[1], "left"))
            cut[s] = H.Coin(s, c.ts[:k].copy(), c.o[:k].copy(), c.h[:k].copy(), c.l[:k].copy(), c.c[:k].copy(),
                            c.v[:k].copy(), c.qv[:k].copy())
        fund = {s: (ts[ts < SELECT[1]], r[ts < SELECT[1]]) for s, (ts, r) in synth["fund"].items()}
        H.install(cut, fund)
        mk = H.Market(SYMS, SELECT, name="select")
        for spec in MAP_SYSTEMS:
            sig = H.system_signals(mk, spec)
            if not weekends:
                keep = ~RO.is_weekend_close(RO.close_ms_of(H, SYMS, sig))
                sig = {"tf": sig["tf"], "k": sig["k"][keep], "j": sig["j"][keep], "side": sig["side"][keep]}
            base = H.run_signals(mk, [(sig, 0)], H.R_BASE, "base")
            c2 = H.run_signals(mk, [(sig, 0)], H.R_BASE, "x2")
            ok, why = H.wide_eligible(base, c2)
            rows.append({**{k: spec[k] for k in ("id", "family", "name", "strategy", "kind", "tf", "gate")},
                         "eligible": ok, "fail": why, "score": base["mean_lnM"], "median_M": base["median_M"]})
    finally:
        RO._restore(H, snap)
    H._EVENTS.clear()
    H._SIGS.clear()
    return rows


def test_select_map_by_timeframe_against_select_json(synth, monkeypatch, tmp_path):
    """The map's per-timeframe block (all four timeframes) sets the select step's rows (weekends included) beside the
    map's (weekends skipped); the official members rerun with weekends on the cut data equal select.json's scores;
    DeepSeek figures only in private (D11)."""
    ctx = _ctx(synth, monkeypatch)
    full = _select_rows_on_cut(synth, weekends=True)
    no_wk = {r["id"]: r for r in _select_rows_on_cut(synth, weekends=False)}
    pub_rows, priv_rows = H.redact_rows(full)
    pub_p, priv_p = tmp_path / "select.json", tmp_path / "wide_select_private.json"
    pub_p.write_text(json.dumps({"rows": pub_rows, "picks": ["F2:AAA:1h:NONE"]}))
    priv_p.write_text(json.dumps({"rows": priv_rows}))
    assert "score" not in next(r for r in pub_rows if r["kind"] == "ds")         # the public select file is redacted
    monkeypatch.setattr(RO, "_select_paths", lambda c: (str(pub_p), str(priv_p)))
    official = ["F2:AAA:1h:NONE", "F3:DSX:30m:NONE"]
    pub, priv = RO.select_weekend_map(ctx, H, official)
    by_id = {r["id"]: r for r in full}
    assert pub["select_table"]["private_rows"] and pub["select_table"]["select_json_sha256"] == H.sha256_file(
        str(pub_p))
    # the cut data reproduce the select step: rerun with weekends == select.json's score, exactly
    assert pub["select_json_check"]["n"] == pub["select_json_check"]["n_equal"] == 1          # public: no DeepSeek
    assert priv["select_json_check"]["n"] == priv["select_json_check"]["n_equal"] == 2
    assert priv["select_json_check"]["max_abs_diff"] == 0.0
    assert priv["rows"]["F3:DSX:30m:NONE"]["score_with_weekends_rerun"] == by_id["F3:DSX:30m:NONE"]["score"]
    for which, d in (("public", pub), ("private", priv)):
        bt = d["by_timeframe"]
        assert list(bt) == list(H.TF_ORDER), which
        for tf in H.TF_ORDER:
            rt = [s for s in MAP_SYSTEMS if s["tf"] == tf]
            money = [s for s in rt if which == "private" or s["kind"] != "ds"]
            b = bt[tf]
            assert b["systems"] == len(rt) and b["systems_in_figures"] == len(money) == b["paired_systems"]
            assert b["systems_not_in_select_json"] == 0
            assert b["eligible_with_weekends"] == sum(by_id[s["id"]]["eligible"] for s in rt)
            assert b["eligible_without_weekends"] == sum(no_wk[s["id"]]["eligible"] for s in rt)
            if money:
                assert b["median_score_with_weekends"] == pytest.approx(
                    float(np.median([by_id[s["id"]]["score"] for s in money])))
                assert b["median_score_without_weekends"] == pytest.approx(
                    float(np.median([no_wk[s["id"]]["score"] for s in money])))
                assert b["higher_without_weekends"] + b["lower_without_weekends"] + b["equal"] == len(money)
            else:
                assert b["median_score_with_weekends"] is None and b["median_score_change"] is None
            assert b["picks_with_weekends_official"] == [i for i in official if i.split(":")[2] == tf]
            assert set(b["picks_without_weekends_map"]) <= set(d["picks"])
    assert pub["by_timeframe"]["30m"]["systems_in_figures"] == 0 and priv["by_timeframe"]["30m"]["paired_systems"] == 1
    ds_ids = {"F3:DSX:30m:NONE"}
    assert H.d11_problems({"O1_select_map": pub}, ds_ids) == []
    assert H.d11_problems({"O1_select_map": priv}, ds_ids) != []                # the private copy holds the figures


def test_o2_not_run_without_a_verified_pinned_calendar(synth, monkeypatch, tmp_path):
    _cal_tree(tmp_path, monkeypatch, verified=False, pinned=True)
    ctx = _ctx(synth, monkeypatch, picks=[_spec(1, "AAA", "core", "F2")])
    monkeypatch.setattr(RO, "select_weekend_map", lambda ctx, live, off: ({"skipped": "in this test"}, {}))
    RO.run(ctx)
    out = ctx["out"]
    assert out["calendar"]["run"] is False and out["constants"]["variants"] == ["base", "O1", "O1b"]
    t = out["rows"]["pick:F2:AAA:1h:NONE"]["periods"]["test"]
    assert "not verified" in t["O2"]["not_run"] and "mean_lnM" not in t["O2"]
    assert "O1" in out["by_timeframe"] and "O2" not in out["by_timeframe"]
