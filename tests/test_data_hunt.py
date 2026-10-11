"""research/hunt/data_hunt.py: download, checksum, conversion, daily fill, resume, manifest verify. Synthetic zips only
(a local folder with the data.binance.vision layout); nothing is fetched from the network."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import data_hunt as D  # noqa: E402

D.RETRY_SLEEP = 0.0
FIVE, ONE, DAY = 300_000, 60_000, 86_400_000
SYM = "SYNUSDT"
KHEAD = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
         "taker_buy_quote_volume,ignore")


def ms(s: str) -> int:
    return int(np.datetime64(s, "ms").astype(np.int64))


# ------------------------------------------------------------------ synthetic archive
def truth(start: str, end: str, step: int, seed: int, zero_from: str | None = None) -> dict:
    """A bar series on the grid [start, end) as the strings an archive holds, plus a mark series."""
    rng = np.random.default_rng(seed)
    t = np.arange(ms(start), ms(end), step, dtype=np.int64)
    n = len(t)
    c = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    v = np.abs(rng.normal(10, 3, n)) + 0.001
    if zero_from:
        z = t >= ms(zero_from)
        last = c[~z][-1]
        o[z] = h[z] = lo[z] = c[z] = last
        v[z] = 0.0
    qv = v * c
    m = c * (1 + rng.normal(0, 0.0003, n))
    S = {"ts": t, "o": [f"{x:.4f}" for x in o], "h": [f"{x:.4f}" for x in h], "l": [f"{x:.4f}" for x in lo],
         "c": [f"{x:.4f}" for x in c], "v": [f"{x:.3f}" for x in v], "qv": [f"{x:.5f}" for x in qv],
         "mo": [f"{x:.5f}" for x in m * 0.9999], "mh": [f"{x:.5f}" for x in m * 1.0004],
         "ml": [f"{x:.5f}" for x in m * 0.9995], "mc": [f"{x:.5f}" for x in m]}
    return S


def kline_csv(S: dict, idx, step: int, header: bool, us: bool = False, alter: float = 0.0) -> str:
    lines = [KHEAD] if header else []
    for i in idx:
        t = int(S["ts"][i])
        tt = t * 1000 if us else t
        c = S["c"][i] if not alter else f"{float(S['c'][i]) * (1 + alter):.4f}"
        lines.append(f"{tt},{S['o'][i]},{S['h'][i]},{S['l'][i]},{c},{S['v'][i]},{tt + step - 1},{S['qv'][i]},7,0,0,0")
    return "\n".join(lines) + "\n"


def mark_csv(S: dict, idx, step: int, header: bool) -> str:
    lines = [KHEAD] if header else []
    for i in idx:
        t = int(S["ts"][i])
        lines.append(f"{t},{S['mo'][i]},{S['mh'][i]},{S['ml'][i]},{S['mc'][i]},0,{t + step - 1},0,0,0,0,0")
    return "\n".join(lines) + "\n"


def put(root: str, key: str, csv_text: str, checksum: str | None = "good") -> str:
    """Write <root>/<key> (a zip with one csv) and its .CHECKSUM ('good', 'bad' or None)."""
    p = os.path.join(root, key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(os.path.basename(key)[:-4] + ".csv", csv_text)
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if checksum:
        with open(p + ".CHECKSUM", "w") as fh:
            fh.write(f"{h if checksum == 'good' else '0' * 64}  {os.path.basename(key)}\n")
    return h


def month_idx(S, m):
    a = ms(m + "-01")
    y, mm = map(int, m.split("-"))
    b = ms(f"{y + (mm == 12):04d}-{mm % 12 + 1:02d}-01")
    return np.flatnonzero((S["ts"] >= a) & (S["ts"] < b))


def day_idx(S, d):
    a = ms(d)
    return np.flatnonzero((S["ts"] >= a) & (S["ts"] < a + DAY))


HOLE = ("2024-01-10T06:00", "2024-01-11T02:00")        # whole hours missing from the January kline file
MARK_DAY = "2024-02-05"                                 # a whole day missing from the February mark file
MARK_FEW = ("2024-02-07T10:00", 5)                      # 5 bars without mark (below the 1h threshold)


def make_archive(root: str, sym: str = SYM, bad_mark_checksum: bool = False, seed: int = 1, dup: bool = True) -> dict:
    """Two months of 5m data with: a header in January only, microsecond times in February, the last January bar
    repeated (changed) at the top of the February file, a kline hole with daily files whose bars outside the hole are
    changed (must not be used), a whole mark day missing (daily file present), 5 lone missing marks, a zero-volume
    tail, funding with a header and a duplicate row."""
    S = truth("2024-01-01", "2024-03-01", FIVE, seed, zero_from="2024-02-28")
    kl = f"data/futures/um/monthly/klines/{sym}/5m/"
    mk = f"data/futures/um/monthly/markPriceKlines/{sym}/5m/"
    fr = f"data/futures/um/monthly/fundingRate/{sym}/"
    hole = (S["ts"] >= ms(HOLE[0])) & (S["ts"] < ms(HOLE[1]))
    jan, feb = month_idx(S, "2024-01"), month_idx(S, "2024-02")
    put(root, kl + f"{sym}-5m-2024-01.zip", kline_csv(S, [i for i in jan if not hole[i]], FIVE, header=True))
    rep = kline_csv(S, [jan[-1]], FIVE, header=False, alter=0.01) if dup else ""   # last Jan bar again, changed
    put(root, kl + f"{sym}-5m-2024-02.zip", rep + kline_csv(S, feb, FIVE, header=False, us=True))
    for d in ("2024-01-10", "2024-01-11"):
        idx = day_idx(S, d)
        put(root, f"data/futures/um/daily/klines/{sym}/5m/{sym}-5m-{d}.zip",
            kline_csv(S, [i for i in idx if hole[i]], FIVE, True)
            + kline_csv(S, [i for i in idx if not hole[i]][:3], FIVE, False, alter=0.5))
        put(root, f"data/futures/um/daily/markPriceKlines/{sym}/5m/{sym}-5m-{d}.zip", mark_csv(S, idx, FIVE, True))
    mday = set(day_idx(S, MARK_DAY))
    few = set(np.flatnonzero(S["ts"] >= ms(MARK_FEW[0]))[:MARK_FEW[1]])
    put(root, mk + f"{sym}-5m-2024-01.zip", mark_csv(S, jan, FIVE, True))
    put(root, mk + f"{sym}-5m-2024-02.zip", mark_csv(S, [i for i in feb if i not in mday and i not in few], FIVE, True),
        checksum="bad" if bad_mark_checksum else "good")
    put(root, f"data/futures/um/daily/markPriceKlines/{sym}/5m/{sym}-5m-{MARK_DAY}.zip",
        mark_csv(S, sorted(mday), FIVE, True))
    for m in ("2024-01", "2024-02"):
        t0 = ms(m + "-01")
        rows = ["calc_time,funding_interval_hours,last_funding_rate"]
        for k in range(20):
            rows.append(f"{t0 + k * 8 * 3_600_000 + 3},8,{0.0001 * (k + 1):.8f}")
        rows.insert(2, rows[1].split(",")[0] + ",8,0.99")                 # duplicate calc_time: the first is kept
        put(root, fr + f"{sym}-fundingRate-{m}.zip", "\n".join(rows) + "\n")
    S["hole"] = hole
    S["mark_nan"] = np.array(sorted(few))
    S["dup_index"] = int(jan[-1]) if dup else None
    return S


def f64(strings) -> np.ndarray:
    """The archive's decimal strings as float64 (the stored precision; never narrowed to float32)."""
    return np.array([float(s) for s in strings], np.float64)


# ------------------------------------------------------------------ conversion
def test_build_5m_converts_fills_and_keeps_monthly_values(tmp_path):
    src = str(tmp_path / "src")
    S = make_archive(src)
    out = str(tmp_path / "out")
    rc = D.download(D.DirSource(src), [SYM], "5m", out, "2024-01", "2024-02", workers=3, log=D.Log(None))
    assert rc == 0 and os.path.exists(os.path.join(out, "COMPLETE"))
    with np.load(os.path.join(out, "5m", f"{SYM}.npz")) as z:
        a = {k: z[k] for k in z.files}
    assert sorted(a) == sorted(["ts", "o", "h", "l", "c", "v", "qv", "mo", "mh", "ml", "mc"])
    assert a["ts"].dtype == np.int64 and all(a[k].dtype == np.float64 for k in a if k != "ts")
    assert np.array_equal(a["ts"], S["ts"])                                # hole filled, us -> ms, duplicate dropped
    for k in ("o", "h", "l", "v", "qv"):
        assert np.array_equal(a[k], f64(S[k])), k
    want_c = f64(S["c"])
    i = S["dup_index"]                                   # the repeated open time keeps the later (February) row
    want_c[i] = float(f"{float(S['c'][i]) * 1.01:.4f}")
    assert np.array_equal(a["c"], want_c)
    nan = np.isnan(a["mc"])
    assert np.array_equal(np.flatnonzero(nan), S["mark_nan"])             # 5 lone bars stay NaN, the day is filled
    for k in ("mo", "mh", "ml", "mc"):
        assert np.array_equal(a[k][~nan], f64(S[k])[~nan]), k
    with np.load(os.path.join(out, "funding", f"{SYM}.npz")) as z:
        assert z["ts"].dtype == np.int64 and z["rate"].dtype == np.float64
        assert len(z["ts"]) == 40 and np.all(np.diff(z["ts"]) > 0)
        assert 0.99 not in z["rate"]                                       # the duplicate's first row is kept
    man = json.load(open(os.path.join(out, "manifest.json")))
    info = man["symbols"][0]
    assert info["rows"] == len(S["ts"]) and info["duplicate_rows_dropped"] == 1
    assert info["daily_fill"]["kline_rows_added"] == int(S["hole"].sum())
    assert info["daily_fill"]["mark_bars_filled"] == 288 + int(S["hole"].sum())
    assert info["daily_fill"]["kline_days"] == ["2024-01-10", "2024-01-11"]
    assert info["first_bar"] == "2024-01-01 00:00" and info["last_bar"] == "2024-02-29 23:55"
    assert info["last_nonzero_volume_bar"] == "2024-02-27 23:55"
    assert info["missing_months_funding"] == [] and info["missing_5m_bars_inside_span"] == 0
    assert info["checksum_status_counts"] == {"ok": 6}
    assert info["arrays_sha256"] == D.arrays_sha256(os.path.join(out, "5m", f"{SYM}.npz"))
    for key, h in info["source_zips"].items():                             # every source zip's sha256
        assert h == hashlib.sha256(open(os.path.join(src, key), "rb").read()).hexdigest()
    assert len(info["source_zips"]) == 6 + 2 + 3          # monthly, daily klines, daily marks
    assert not os.path.exists(os.path.join(out, "raw", SYM))              # zips deleted after conversion


def test_checksum_mismatch_month_is_dropped_reported_and_not_complete(tmp_path):
    src = str(tmp_path / "src")
    make_archive(src, bad_mark_checksum=True)
    out = str(tmp_path / "out")
    rc = D.download(D.DirSource(src), [SYM], "5m", out, "2024-01", "2024-02", workers=2, log=D.Log(None))
    assert rc == 1 and not os.path.exists(os.path.join(out, "COMPLETE"))  # a failed file is not a finished download
    info = json.load(open(os.path.join(out, "manifest.json")))["symbols"][0]
    assert info["download_problems"] == {"mk:2024-02": "mismatch"}
    assert D.coin_problems(info) == ["mk:2024-02 mismatch"]
    assert info["missing_months_mark"] == ["2024-02"]
    assert info["checksum_status_counts"] == {"ok": 5, "mismatch": 1}
    assert info["daily_fill"]["daily_status"]["mark"][MARK_DAY] == "ok"   # only that day has a daily mark file
    with np.load(os.path.join(out, "5m", f"{SYM}.npz")) as z:
        feb = z["ts"] >= ms("2024-02-01")
        filled = (z["ts"] >= ms(MARK_DAY)) & (z["ts"] < ms(MARK_DAY) + DAY)
        assert np.isnan(z["mc"][feb & ~filled]).all() and not np.isnan(z["mc"][filled]).any()
    assert os.path.isdir(os.path.join(out, "raw", SYM))                   # zips kept for the rerun
    res = D.problems(out)
    assert not res["complete"] and res["problems"] == {SYM: ["mk:2024-02 mismatch"]} and res["not_built"] == []
    assert D.main(["problems", "--data", out]) == 1
    # the archive is fixed (republished checksum): the rerun rebuilds the coin, fetching only the failed file
    key = f"data/futures/um/monthly/markPriceKlines/{SYM}/5m/{SYM}-5m-2024-02.zip"
    good = hashlib.sha256(open(os.path.join(src, key), "rb").read()).hexdigest()
    with open(os.path.join(src, key + ".CHECKSUM"), "w") as fh:
        fh.write(f"{good}  {os.path.basename(key)}\n")
    again = Counting(D.DirSource(src))
    assert D.download(again, [SYM], "5m", out, "2024-01", "2024-02", workers=2, log=D.Log(None)) == 0
    assert {k for k in again.fetches if k.endswith(".zip")} == {key}
    assert D.problems(out)["complete"] and D.main(["problems", "--data", out]) == 0
    assert not os.path.exists(os.path.join(out, "raw"))
    clean = str(tmp_path / "clean")
    D.download(D.DirSource(src), [SYM], "5m", clean, "2024-01", "2024-02", workers=2, log=D.Log(None))
    assert D.arrays_sha256(f"{out}/5m/{SYM}.npz") == D.arrays_sha256(f"{clean}/5m/{SYM}.npz")


def test_fidelity_funding_checksum_failure_is_not_complete(tmp_path):
    """A funding month that keeps failing its checksum: the coin is written (no funding file), COMPLETE is not."""
    src = str(tmp_path / "src")
    S = truth("2024-03-01", "2024-03-04", ONE, 5)
    put(src, f"data/futures/um/monthly/klines/{SYM}/1m/{SYM}-1m-2024-03.zip",
        kline_csv(S, range(len(S["ts"])), ONE, True))
    put(src, f"data/futures/um/monthly/markPriceKlines/{SYM}/1m/{SYM}-1m-2024-03.zip",
        mark_csv(S, range(len(S["ts"])), ONE, True))
    put(src, f"data/futures/um/monthly/fundingRate/{SYM}/{SYM}-fundingRate-2024-03.zip",
        f"{ms('2024-03-01')},8,0.0001\n", checksum="bad")
    out = str(tmp_path / "fid")
    assert D.download(D.DirSource(src), [SYM], "fidelity", out, "2024-03", "2024-03", 2, D.Log(None)) == 1
    assert not os.path.exists(os.path.join(out, "COMPLETE"))
    info = json.load(open(os.path.join(out, "manifest.json")))["symbols"][0]
    assert info["missing_months_funding"] == ["2024-03"] and info["funding_rows"] == 0
    assert D.problems(out)["problems"] == {SYM: ["fr:2024-03 mismatch"]}


def test_daily_fill_checksum_failure_is_a_problem_and_a_daily_404_is_not(tmp_path):
    src = str(tmp_path / "src")
    make_archive(src)
    day = "2024-01-11"
    key = f"data/futures/um/daily/klines/{SYM}/5m/{SYM}-5m-{day}.zip"
    with open(os.path.join(src, key + ".CHECKSUM"), "w") as fh:
        fh.write("0" * 64 + "  x.zip\n")
    out = str(tmp_path / "out")
    assert D.download(D.DirSource(src), [SYM], "5m", out, "2024-01", "2024-02", workers=2, log=D.Log(None)) == 1
    info = json.load(open(os.path.join(out, "manifest.json")))["symbols"][0]
    assert info["download_problems"] == {} and D.coin_problems(info) == [f"daily klines {day} mismatch"]
    os.remove(os.path.join(src, key))                                     # the day has no daily file at all
    os.remove(os.path.join(src, key + ".CHECKSUM"))
    out2 = str(tmp_path / "out2")
    assert D.download(D.DirSource(src), [SYM], "5m", out2, "2024-01", "2024-02", workers=2, log=D.Log(None)) == 0
    info = json.load(open(os.path.join(out2, "manifest.json")))["symbols"][0]
    assert info["daily_fill"]["daily_status"]["klines"][day] == "404" and D.coin_problems(info) == []


def test_problems_on_a_folder_without_manifest_or_with_a_coin_not_built(tmp_path):
    assert D.main(["problems", "--data", str(tmp_path / "none")]) == 2
    src = str(tmp_path / "src")
    make_archive(src)
    out = str(tmp_path / "out")
    assert D.download(D.DirSource(src), [SYM, "GONEUSDT"], "5m", out, "2024-01", "2024-02", 2, D.Log(None)) == 1
    res = D.problems(out)
    assert res["not_built"] == ["GONEUSDT"] and res["problems"] == {} and not res["complete"]
    assert D.main(["problems", "--data", out]) == 2


def test_fetch_verified_statuses(tmp_path):
    src = str(tmp_path / "src")
    good = put(src, "a/x.zip", "1,2\n")
    put(src, "a/y.zip", "1,2\n", checksum="bad")
    put(src, "a/z.zip", "1,2\n", checksum=None)
    s = D.DirSource(src)
    assert D.fetch_verified(s, "a/x.zip", str(tmp_path / "d/x.zip"), True) == ("ok", good)
    assert D.fetch_verified(s, "a/y.zip", str(tmp_path / "d/y.zip"), True)[0] == "mismatch"
    assert not os.path.exists(tmp_path / "d/y.zip")
    assert D.fetch_verified(s, "a/z.zip", str(tmp_path / "d/z.zip"), True)[0] == "nock"
    assert D.fetch_verified(s, "a/none.zip", str(tmp_path / "d/n.zip"), True) == ("404", None)


# ------------------------------------------------------------------ resume
class Counting:
    def __init__(self, inner, fail_after=None):
        self.inner, self.fetches, self.lists, self.fail_after = inner, {}, 0, fail_after

    def list(self, prefix):
        self.lists += 1
        return self.inner.list(prefix)

    def fetch(self, key):
        if self.fail_after is not None and sum(self.fetches.values()) >= self.fail_after:
            raise OSError("network down")
        self.fetches[key] = self.fetches.get(key, 0) + 1
        return self.inner.fetch(key)


def test_resume_after_interruption_and_skip_when_done(tmp_path):
    src = str(tmp_path / "src")
    make_archive(src)
    clean = str(tmp_path / "clean")
    D.download(D.DirSource(src), [SYM], "5m", clean, "2024-01", "2024-02", workers=1, log=D.Log(None))
    out = str(tmp_path / "out")
    first = Counting(D.DirSource(src), fail_after=5)                       # dies after 5 fetches
    assert D.download(first, [SYM], "5m", out, "2024-01", "2024-02", workers=1, log=D.Log(None)) == 1
    assert not os.path.exists(os.path.join(out, "COMPLETE"))
    got_before = {k for k in first.fetches if k.endswith(".zip") and k + ".CHECKSUM" in first.fetches}
    assert got_before
    second = Counting(D.DirSource(src))
    assert D.download(second, [SYM], "5m", out, "2024-01", "2024-02", workers=1, log=D.Log(None)) == 0
    assert not (got_before & set(second.fetches))                         # finished zips were not fetched again
    assert D.arrays_sha256(os.path.join(out, "5m", f"{SYM}.npz")) == \
        D.arrays_sha256(os.path.join(clean, "5m", f"{SYM}.npz"))
    third = Counting(D.DirSource(src))
    assert D.download(third, [SYM], "5m", out, "2024-01", "2024-02", workers=1, log=D.Log(None)) == 0
    assert third.fetches == {} and third.lists == 0                       # a finished coin is skipped
    with pytest.raises(D.DataError):                                     # same folder, other parameters
        D.download(third, [SYM], "5m", out, "2024-01", "2024-03", workers=1, log=D.Log(None))


# ------------------------------------------------------------------ manifest verify
def test_verify_against_reference(tmp_path):
    src = str(tmp_path / "src")
    make_archive(src)
    make_archive(src, sym="SYNBUSDT", seed=2)
    syms = [SYM, "SYNBUSDT"]
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    assert D.download(D.DirSource(src), syms, "5m", a, "2024-01", "2024-02", workers=2, log=D.Log(None)) == 0
    assert D.main(["download", "--kind", "5m", "--out", b, "--symbols", ",".join(syms), "--from", "2024-01",
                   "--to", "2024-02", "--source-dir", src, "--workers", "2"]) == 0
    for s in syms:                                                         # same arrays -> same file bytes
        assert D.sha256_file(f"{a}/5m/{s}.npz") == D.sha256_file(f"{b}/5m/{s}.npz")
    ref = D.make_ref(a)
    rp = str(tmp_path / "ref.json")
    json.dump(ref, open(rp, "w"))
    assert D.verify(f"{b}/manifest.json", rp, b)["ok"]
    assert D.main(["verify", "--data", b, "--ref", rp, "--report", str(tmp_path / "rep.json")]) == 0
    # one changed value in a converted file
    p = f"{b}/5m/{SYM}.npz"
    with np.load(p) as z:
        arr = {k: z[k].copy() for k in z.files}
    arr["c"][100] += 0.5
    D.save_npz(p, arr)
    rep = D.verify(f"{b}/manifest.json", rp, b)
    assert not rep["ok"] and any("file content" in x for x in rep["differences"])
    assert D.main(["verify", "--data", b, "--ref", rp]) == 1
    # a field the hunt reads
    man = json.load(open(f"{a}/manifest.json"))
    man["symbols"][0]["last_nonzero_volume_bar"] = "2024-02-28 00:00"
    json.dump(man, open(str(tmp_path / "m2.json"), "w"))
    rep = D.verify(str(tmp_path / "m2.json"), rp)
    assert not rep["ok"] and "last_nonzero_volume_bar" in rep["differences"][0]
    # a missing coin
    man = json.load(open(f"{a}/manifest.json"))
    man["symbols"] = man["symbols"][:1]
    json.dump(man, open(str(tmp_path / "m3.json"), "w"))
    assert not D.verify(str(tmp_path / "m3.json"), rp)["ok"]
    # a reference without array hashes (a plain coins30 manifest) is refused unless asked
    plain = json.load(open(f"{a}/manifest.json"))
    for r in plain["symbols"]:
        for k in ("arrays_sha256", "arrays_sha256_funding", "content_sha256"):
            r.pop(k)
    json.dump(plain, open(str(tmp_path / "plain.json"), "w"))
    assert not D.verify(f"{a}/manifest.json", str(tmp_path / "plain.json"))["ok"]
    assert D.verify(f"{a}/manifest.json", str(tmp_path / "plain.json"), allow_meta_only=True)["ok"]


def test_refman_refuses_files_that_differ_from_their_manifest(tmp_path):
    src = str(tmp_path / "src")
    make_archive(src)
    a = str(tmp_path / "a")
    D.download(D.DirSource(src), [SYM], "5m", a, "2024-01", "2024-02", workers=2, log=D.Log(None))
    with open(f"{a}/funding/{SYM}.npz", "ab") as fh:
        fh.write(b"x")
    with pytest.raises(D.DataError):
        D.make_ref(a)


def test_prove_one_month_against_an_existing_folder(tmp_path):
    src = str(tmp_path / "src")
    make_archive(src, dup=False)
    a = str(tmp_path / "a")
    D.download(D.DirSource(src), [SYM], "5m", a, "2024-01", "2024-02", workers=2, log=D.Log(None))
    res = D.prove(D.DirSource(src), SYM, "2024-02", a, str(tmp_path / "w"))
    assert res["reproduced"] and res["rows_new"] == res["rows_ref"] == 29 * 288
    assert not os.path.exists(tmp_path / "w")


# ------------------------------------------------------------------ fidelity kind
def test_fidelity_kind_writes_1m_with_the_1h_mark_threshold(tmp_path):
    src = str(tmp_path / "src")
    S = truth("2024-03-01", "2024-03-04", ONE, 5)
    kl = f"data/futures/um/monthly/klines/{SYM}/1m/{SYM}-1m-2024-03.zip"
    mk = f"data/futures/um/monthly/markPriceKlines/{SYM}/1m/{SYM}-1m-2024-03.zip"
    put(src, kl, kline_csv(S, range(len(S["ts"])), ONE, True))
    day2 = set(day_idx(S, "2024-03-02"))                                  # a whole mark day missing, daily present
    few = set(day_idx(S, "2024-03-03")[100:159])                          # 59 bars: under 60, not fetched
    put(src, mk, mark_csv(S, [i for i in range(len(S["ts"])) if i not in day2 and i not in few], ONE, False))
    put(src, f"data/futures/um/daily/markPriceKlines/{SYM}/1m/{SYM}-1m-2024-03-02.zip", mark_csv(S, sorted(day2), ONE,
                                                                                                  True))
    put(src, f"data/futures/um/monthly/fundingRate/{SYM}/{SYM}-fundingRate-2024-03.zip",
        f"{ms('2024-03-01')},8,0.0001\n{ms('2024-03-01') + 8 * 3_600_000},8,0.0002\n")
    out = str(tmp_path / "fid")
    assert D.download(D.DirSource(src), [SYM], "fidelity", out, "2024-03", "2024-03", 2, D.Log(None)) == 0
    with np.load(os.path.join(out, "1m", f"{SYM}.npz")) as z:
        assert sorted(z.files) == sorted(["ts", "o", "h", "l", "c", "v", "qv", "mo", "mh", "ml", "mc"])
        assert np.array_equal(z["ts"], S["ts"]) and np.all(np.diff(z["ts"]) == ONE)
        assert np.isnan(z["mc"]).sum() == 59
    info = json.load(open(os.path.join(out, "manifest.json")))["symbols"][0]
    assert info["interval"] == "1m" and info["npz_1m"] == f"1m/{SYM}.npz"
    assert info["missing_1m_bars_inside_span"] == 0 and info["daily_fill"]["mark_days"] == ["2024-03-02"]
    assert info["daily_fill"]["mark_bars_filled"] == 1440 and info["funding_rows"] == 2


# ------------------------------------------------------------------ symbols, coins, shell
def test_symbol_sources(tmp_path):
    md = tmp_path / "U.md"
    md.write_text("# x\n\n## The 30 coins\n\n| rank | symbol | v |\n|---:|---|---:|\n| 1 | BTCUSDT | 1 |\n"
                  "| 2 | ETHUSDT | 2 |\n\nNext 10\n\n## Other\n| 31 | XLMUSDT | 0 |\n")
    assert D.symbols_from_md(str(md)) == ["BTCUSDT", "ETHUSDT"]
    md.write_text(md.read_text() + "\nUniverse (copy-paste): BTCUSDT ETHUSDT SOLUSDT\n")
    assert D.symbols_from_md(str(md)) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    uj = tmp_path / "u.json"
    uj.write_text(json.dumps({"symbols": ["AUSDT", "BUSDT"]}))
    assert D.resolve_symbols("X,Y", str(md), str(uj))[0] == ["X", "Y"]
    assert D.resolve_symbols(None, str(md), str(uj))[0] == ["AUSDT", "BUSDT"]
    assert D.resolve_symbols(None, str(md), str(tmp_path / "none.json"))[0] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    with pytest.raises(D.DataError):
        D.resolve_symbols(None, None, str(tmp_path / "none.json"))


def test_bootstrap_shell_syntax():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    p = os.path.join(ROOT, "research", "hunt", "bootstrap.sh")
    r = subprocess.run([bash, "-n", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_bootstrap_shellcheck():
    sc = shutil.which("shellcheck")
    if not sc:
        pytest.skip("no shellcheck")
    r = subprocess.run([sc, os.path.join(ROOT, "research", "hunt", "bootstrap.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_verify_against_the_hunt_data_manifest_format(tmp_path):
    """research/hunt/data_manifest.json: {"manifest": <the data's manifest copy>, "content": {SYM: {"5m", "funding"}}}
    with the hunt's own identity hash (the arrays a study reads)."""
    src = str(tmp_path / "src")
    make_archive(src)
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    for o in (a, b):
        D.download(D.DirSource(src), [SYM], "5m", o, "2024-01", "2024-02", workers=2, log=D.Log(None))
    man = json.load(open(f"{a}/manifest.json"))
    plain = {"symbols": [{k: v for k, v in r.items() if "sha256" not in k} for r in man["symbols"]]}
    dm = {"manifest": plain, "content": {SYM: {"5m": D.content_sha(f"{a}/5m/{SYM}.npz", "5m"),
                                                "funding": D.content_sha(f"{a}/funding/{SYM}.npz", "funding")}}}
    rp = str(tmp_path / "data_manifest.json")
    json.dump(dm, open(rp, "w"))
    rep = D.verify(f"{b}/manifest.json", rp, b)
    assert rep["ok"] and rep["hashes_compared"] == ["content_5m", "content_funding"]
    p = f"{b}/5m/{SYM}.npz"
    with np.load(p) as z:
        arr = {k: z[k].copy() for k in z.files}
    arr["mc"][5] += 1.0                                     # a mark value: not part of the hunt's identity
    D.save_npz(p, arr)
    rep = D.verify(f"{b}/manifest.json", rp, b)
    assert not rep["ok"] and all("arrays_sha256" in x for x in rep["differences"])   # caught only by its manifest
    arr["qv"][7] += 1.0                                     # a quote volume: part of it
    D.save_npz(p, arr)
    rep = D.verify(f"{b}/manifest.json", rp, b)
    assert any("content_5m) differs from the reference" in x for x in rep["differences"])
    dm["manifest"]["symbols"][0]["last_nonzero_volume_bar"] = "2024-02-28 00:00"
    json.dump(dm, open(rp, "w"))
    assert any("last_nonzero_volume_bar" in x for x in D.verify(f"{a}/manifest.json", rp)["differences"])


def test_republished_mark_values_pass_the_hunt_identity_but_not_the_all_keys_reference(tmp_path):
    """bootstrap step 5 checks both references: data_manifest.json (the arrays the hunt reads) and data_ref_5m.json
    (refman, every key: the mark columns too)."""
    src = str(tmp_path / "src")
    make_archive(src)
    a = str(tmp_path / "a")
    D.download(D.DirSource(src), [SYM], "5m", a, "2024-01", "2024-02", workers=2, log=D.Log(None))
    man = json.load(open(f"{a}/manifest.json"))
    dm = {"manifest": {"symbols": [{k: v for k, v in r.items() if "sha256" not in k} for r in man["symbols"]]},
          "content": {SYM: {"5m": D.content_sha(f"{a}/5m/{SYM}.npz", "5m"),
                            "funding": D.content_sha(f"{a}/funding/{SYM}.npz", "funding")}}}
    rp, ra = str(tmp_path / "data_manifest.json"), str(tmp_path / "data_ref_5m.json")
    json.dump(dm, open(rp, "w"))
    assert D.main(["refman", "--data", a, "--out", ra]) == 0
    S2 = truth("2024-01-01", "2024-03-01", FIVE, 1, zero_from="2024-02-28")   # every January mark value +1%
    for k in ("mo", "mh", "ml", "mc"):
        S2[k] = [f"{float(x) * 1.01:.5f}" for x in S2[k]]
    put(src, f"data/futures/um/monthly/markPriceKlines/{SYM}/5m/{SYM}-5m-2024-01.zip",
        mark_csv(S2, month_idx(S2, "2024-01"), FIVE, True))
    b = str(tmp_path / "b")
    assert D.download(D.DirSource(src), [SYM], "5m", b, "2024-01", "2024-02", workers=2, log=D.Log(None)) == 0
    assert D.verify(f"{b}/manifest.json", rp, b)["ok"]                    # the hunt's arrays are the same
    rep = D.verify(f"{b}/manifest.json", ra, b)
    assert not rep["ok"] and any("arrays_sha256 differs from the reference" in x for x in rep["differences"])
    assert D.main(["verify", "--data", b, "--ref", ra]) == 1


def test_content_sha_is_the_hunt_identity(tmp_path):
    """data_hunt.content_sha must equal research/hunt/hunt.py's own data identity (when that code has one)."""
    H = pytest.importorskip("research.hunt.hunt")
    if not hasattr(H, "file_content_sha"):
        pytest.skip("research/hunt/hunt.py has no file_content_sha")
    src = str(tmp_path / "src")
    make_archive(src)
    a = str(tmp_path / "a")
    D.download(D.DirSource(src), [SYM], "5m", a, "2024-01", "2024-02", workers=2, log=D.Log(None))
    for kind, p in (("5m", f"{a}/5m/{SYM}.npz"), ("funding", f"{a}/funding/{SYM}.npz")):
        assert D.content_sha(p, kind) == H.file_content_sha(p, kind)
        assert tuple(D.CONTENT_KEYS[kind]) == tuple(H.CONTENT_KEYS[kind])
