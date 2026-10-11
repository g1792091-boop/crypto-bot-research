"""huntbot lineup and account variants (synthetic data only, no real price, no outcome of any study):

- ``lineup suggest`` takes test.json's own ``lineup`` field (PREREG_HUNT_WIDE W 12, written by research/hunt/hunt.py
  ``lineup_table``): 정식 -> r0.5 and r1, 참고 -> r0.5, excluded -> no account, the basket of two or more 정식 picks;
  nothing when the field is missing or disagrees with the verdict; never a goal-size account;
- the goal-size variants are the R1 board's machines (W 7.3, ``reads_a.cell_overrides``): A2 = machine A at 2%
  (B = equity / 6 as written, the cap scaled), B5 = machine B (goal-mode) at 5%; the retired W 7 sizing read
  (goal2 / goal5, B scaled with r) is gone; a goal-size account needs the owners' decision (W 7.1 rule 6);
- the tested variants keep the reviewed parameter vector bit for bit; huntbot no longer needs ``hunt.SIZING_RS``.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt import reads_a as RA  # noqa: E402

from huntbot import config as CFG  # noqa: E402
from huntbot import engine as E  # noqa: E402
from huntbot import runner as RN  # noqa: E402
from huntbot import systems as S  # noqa: E402

IDS = ("F1:E1:1h:NONE", "F2:A:1h:G1", "F2:B:4h:NONE", "F2:D:15m:G1", "F3:C:1h:G1", "F1:E2:4h:G1")


def _spec(sid: str) -> dict:
    fam, name, tf, gate = sid.split(":")
    return {"id": sid, "family": fam, "name": name, "tf": tf, "gate": gate,
            "kind": {"F1": "hunt", "F2": "core", "F3": "ds"}[fam]}


BY_ID = {i: _spec(i) for i in IDS}
ALIASES = {"v1:E2:4h": "F1:E2:4h:G1"}


# ---------------------------------------------------------------- the test step's own lineup table
def _block(mean_lnM=0.02, median_M=1.01, d_a=0.01, d_b=0.01, cost2=0.01, dd=0.2, bust=False, lnM=None):
    return {"base": {"mean_lnM": mean_lnM, "median_M": median_M, "max_dd": dd, "bust": bust,
                     "lnM": lnM if lnM is not None else [0.02, 0.01, 0.03, 0.02]},
            "cost2": {"mean_lnM": cost2}, "checks": {"mean_d_a": d_a, "mean_d_b": d_b}}


def _write(root, study: str, doc: dict) -> None:
    d = os.path.join(root, "research", "hunt", "out", study)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "test.json"), "w") as fh:
        json.dump(doc, fh, ensure_ascii=False)


def _wide_doc():
    """Batch 1 of four picks: two pass (정식), one fails but meets the seven 참고 conditions, one fails them
    (excluded: cost x2 and drawdown)."""
    tested = [{"id": "F2:A:1h:G1", "pick_no": 1, "batch": 1}, {"id": "F3:C:1h:G1", "pick_no": 2, "batch": 1},
              {"id": "F2:B:4h:NONE", "pick_no": 3, "batch": 1}, {"id": "F2:D:15m:G1", "pick_no": 4, "batch": 1}]
    blocks = {"F2:A:1h:G1": _block(), "F2:B:4h:NONE": _block(), "F3:C:1h:G1": _block(),
              "F2:D:15m:G1": _block(cost2=-0.01, dd=0.6)}
    passing = ["F2:A:1h:G1", "F2:B:4h:NONE"]
    lu = H.lineup_table(tested, blocks, "picks", passing)
    return {"picks": tested, "verdict": {"wide_pass": True, "label": "picks", "passing": passing}, "lineup": lu}


def _v1_doc(passed: bool, block: dict):
    spec = {"id": "v1:E2:4h", "name": "E2", "tf": "4h", "gate": "G1"}
    lu = H.lineup_table([{**spec, "pick_no": 1, "batch": 1}], {spec["id"]: block}, "pick",
                        [spec["id"]] if passed else [])
    return {"pick": spec, "verdict": {"v1_pass": passed, "label": "pick"}, "lineup": lu}


def test_suggest_follows_the_test_lineup_field(tmp_path):
    wide = _wide_doc()
    assert wide["lineup"]["정식"] == ["F2:A:1h:G1", "F2:B:4h:NONE"] and wide["lineup"]["참고"] == ["F3:C:1h:G1"]
    assert wide["lineup"]["excluded"] == ["F2:D:15m:G1"]
    _write(tmp_path, "wide", wide)
    _write(tmp_path, "v1", _v1_doc(False, _block(mean_lnM=-0.01)))         # failed and fails the 참고 rule
    res = S.suggest_lineup(str(tmp_path))
    got = [(a.get("system") or "basket", a["label"], a["variant"]) for a in res["accounts"]]
    assert got == [("F2:A:1h:G1", "정식", "r0.5"), ("F2:A:1h:G1", "정식", "r1"), ("F3:C:1h:G1", "참고", "r0.5"),
                   ("F2:B:4h:NONE", "정식", "r0.5"), ("F2:B:4h:NONE", "정식", "r1"),
                   ("basket", "정식", "r0.5"), ("basket", "정식", "r1")]
    basket = [a for a in res["accounts"] if a.get("basket")][0]
    assert basket["basket"] == ["F2:A:1h:G1", "F2:B:4h:NONE"] and basket["pick_nos"] == [1, 3]
    ex = {(x["study"], x["system"]): x["why"] for x in res["excluded"]}
    assert ex == {("v1", "v1:E2:4h"): ["mean_lnM"], ("wide", "F2:D:15m:G1"): ["cost_x2", "max_dd"]}
    assert res["studies"]["wide"] == {"정식": 2, "참고": 1, "excluded": 1}
    assert res["studies"]["v1"] == {"정식": 0, "참고": 0, "excluded": 1}
    # the proposal is a valid lineup file as it stands
    accts = S.parse_lineup(res, BY_ID, ALIASES)
    assert len(accts) == 7 and not any(S.variants()[a["variant"]]["read"] for a in accts)


def test_suggest_v1_pass_and_v1_reference(tmp_path):
    _write(tmp_path, "v1", _v1_doc(True, _block()))
    res = S.suggest_lineup(str(tmp_path))
    assert [(a["system"], a["label"], a["variant"]) for a in res["accounts"]] == [
        ("v1:E2:4h", "정식", "r0.5"), ("v1:E2:4h", "정식", "r1")]
    assert res["studies"]["wide"] == "no test.json: nothing proposed"
    _write(tmp_path, "v1", _v1_doc(False, _block()))                       # fails the test, meets the 참고 rule
    res = S.suggest_lineup(str(tmp_path))
    assert [(a["system"], a["label"], a["variant"]) for a in res["accounts"]] == [("v1:E2:4h", "참고", "r0.5")]
    assert S.parse_lineup(res, BY_ID, ALIASES)[0]["id"] == "F1:E2:4h:G1|r0.5"


def test_suggest_guesses_nothing(tmp_path):
    wide = _wide_doc()
    _write(tmp_path, "wide", {k: v for k, v in wide.items() if k != "lineup"})      # no lineup field
    res = S.suggest_lineup(str(tmp_path))
    assert res["accounts"] == [] and "no 'lineup' field" in res["studies"]["wide"]
    bad = json.loads(json.dumps(wide))
    bad["verdict"]["passing"] = ["F2:A:1h:G1"]                        # 정식 must be exactly the research PASS
    _write(tmp_path, "wide", bad)
    res = S.suggest_lineup(str(tmp_path))
    assert res["accounts"] == [] and "PASS" in res["studies"]["wide"]
    bad = json.loads(json.dumps(wide))
    bad["lineup"]["picks"]["F2:D:15m:G1"]["lineup"] = "goal"              # an unknown tier
    _write(tmp_path, "wide", bad)
    assert S.suggest_lineup(str(tmp_path))["accounts"] == []
    bad = json.loads(json.dumps(wide))
    bad["lineup"]["참고"] = []                                          # the lists must agree with 'picks'
    _write(tmp_path, "wide", bad)
    assert S.suggest_lineup(str(tmp_path))["accounts"] == []
    _write(tmp_path, "v1", {"pick": {"id": "v1:E2:4h"}, "verdict": {"v1_pass": False},
                            "lineup": H.lineup_table([{"id": "v1:E2:4h", "pick_no": 1}], {"v1:E2:4h": _block()},
                                                     "no pick, fail", [])})
    res = S.suggest_lineup(str(tmp_path))                              # 'no pick, fail' is excluded (H 15)
    assert res["accounts"] == [] and res["excluded"][0]["why"] == ["no pick, fail"]


# ---------------------------------------------------------------- variants = the R1 board's machines
def test_goal_size_variants_are_the_r1_machines():
    v = S.variants()
    for name, machine, r in S.GOAL_CELLS:
        r_, ov = RA.cell_overrides(machine, r)
        assert v[name]["r"] == r_ and v[name]["overrides"] == ov and v[name]["read"] and v[name]["machine"] == machine
        assert np.array_equal(E.params_of(v[name]),
                              H.with_overrides(H.params(r_, "base", H.RISK_CAP, H.START_WALLET), ov))
    a2, b5 = E.params_of(v["A2"]), E.params_of(v["B5"])
    assert a2[H.PR_CAP] == pytest.approx(0.16) and a2[H.PR_BDIV] == H.B_DIV                # B = equity / 6
    assert a2[H.PR_MAXPOS] == H.MAX_POS and a2[H.PR_BRK_Q1] == 0
    assert b5[H.PR_R] == 0.05 and b5[H.PR_CAP] == pytest.approx(0.20) and b5[H.PR_MAXPOS] == 4
    assert b5[H.PR_BDIV] == 4.0 and b5[H.PR_BRK_Q1] == 1 and b5[H.PR_LEVMAX] == RA.GOAL_MODE_LEVMAX
    # the tested accounts: the reviewed vector, bit for bit, no override
    assert np.array_equal(E.params_of(v["r0.5"]), H.params())
    assert np.array_equal(E.params_of(v["r1"]), H.params(H.R_ONE))
    assert not v["r0.5"]["read"] and not v["r1"]["read"]


def test_engine_api_without_sizing_rs():
    assert "SIZING_RS" not in RN.ENGINE_API and "with_overrides" in RN.ENGINE_API
    assert RN.engine_api_problems() == []


def test_goal_size_account_needs_the_owners_decision():
    for v in ("A2", "B5"):
        with pytest.raises(S.LineupError, match="owners"):
            S.parse_lineup({"accounts": [{"system": "F2:A:1h:G1", "label": "정식", "variant": v}]}, BY_ID, ALIASES)
        with pytest.raises(S.LineupError, match="owners"):
            S.parse_lineup({"accounts": [{"system": "F2:A:1h:G1", "label": "정식", "variant": v,
                                          "owners_decision": "  "}]}, BY_ID, ALIASES)
    ok = S.parse_lineup({"accounts": [{"system": "F2:A:1h:G1", "label": "정식", "variant": "B5",
                                       "owners_decision": "두 분 2026-11-20"}]}, BY_ID, ALIASES)
    assert ok[0]["id"] == "F2:A:1h:G1|B5" and ok[0]["owners_decision"] == "두 분 2026-11-20"
    assert "시험 안 함" in S.variants()["B5"]["ko"] and "목표 모드" in S.variants()["B5"]["ko"]
    for old, new in S.RETIRED_VARIANTS.items():                     # the retired sizing read is refused by name
        with pytest.raises(S.LineupError, match=new):
            S.parse_lineup({"accounts": [{"system": "F2:A:1h:G1", "label": "참고", "variant": old,
                                          "owners_decision": "x"}]}, BY_ID, ALIASES)
    plain = S.parse_lineup({"accounts": [{"system": "F2:A:1h:G1", "label": "정식", "variant": "r1",
                                          "owners_decision": "ignored"}]}, BY_ID, ALIASES)
    assert plain[0]["owners_decision"] is None


def _rising_market():
    """One synthetic coin: flat, then a steady rise (one long stays open)."""
    s0 = CFG.day_ms("2022-03-01")
    n_pre, n = 288, 288
    px = [100.0] * n_pre + list(100.0 + 0.02 * np.arange(n))
    arr = np.asarray([(p, p * 1.001, p * 0.999, p) for p in px])
    ts = s0 - n_pre * H.FIVE + np.arange(len(px), dtype=np.int64) * H.FIVE
    c = H.Coin("AUSDT", ts, arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], np.full(len(px), 1e6), np.full(len(px), 1e9),
               last_ms=2 ** 62)
    H.install({"AUSDT": c}, {})
    mk = H.Market(["AUSDT"], (s0, s0 + 2 * H.DAY_MS), name="lineup-test")
    seg = mk.b_t[mk.b_off[0]:mk.b_off[1]]
    i = int(np.searchsorted(seg, 10))
    cands = {"t": np.array([10]), "bi": np.array([mk.b_off[0] + i]), "coin": np.array([0]), "side": np.array([1]),
             "d0": np.array([1.5]), "s0": np.array([0]), "s1": np.array([0]), "prio": np.array([0.0]),
             "src": np.array([0]), "close": np.array([s0 + 10 * H.FIVE]), "j": np.array([0])}
    bank = type("Bk", (), {"s_ct": np.zeros(0, np.int64), "s_h": np.zeros(0), "s_l": np.zeros(0),
                           "s_atr": np.zeros(0)})()
    return mk, bank, cands


def test_b5_account_runs_at_the_goal_mode_size():
    """Synthetic bars: the B5 account's first unit risks 5% of the same equity (10 x the r0.5 account's)."""
    mk, bank, cands = _rising_market()
    v = S.variants()
    raw05 = H.simulate(mk, bank, cands, prm=E.params_of(v["r0.5"]))
    raw5 = H.simulate(mk, bank, cands, prm=E.params_of(v["B5"]))
    u05, u5 = float(raw05[3][0, H.RF_U]), float(raw5[3][0, H.RF_U])
    assert u05 == pytest.approx(0.005 * H.START_WALLET) and u5 == pytest.approx(0.05 * H.START_WALLET)
