"""research/hiwr/data.py on a fake archive (no network): only the kit's months are asked for, every zip is
checksum-verified, daily files fill only absent minutes, zero-volume minutes are dropped, a missing mark minute takes
the last-price bar, funding lands on its floored calc minute; the content hashes are the hunt's; every load checks
them and cuts at the period end before anything else; chart frames come from the cut arrays into hiwr's own folder;
the two cross-checks of section 3."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import urllib.error
import zipfile

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from research.hiwr import data as D  # noqa: E402

MIN = 60_000
DAY = 86_400_000
SYM = "AAAUSDT"
JAN = D.ms("2020-01-01")


def _zip(name: str, text: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def _klines(ts, o, h, l, c, v, header=True) -> str:
    rows = ["open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
            "taker_buy_quote_volume,ignore"] if header else []
    for t, a, b, x, y, z in zip(ts, o, h, l, c, v):
        a, b, x, y, z = (float(q) for q in (a, b, x, y, z))
        rows.append(f"{int(t)},{a!r},{b!r},{x!r},{y!r},{z!r},{int(t) + 59_999},{z * y!r},1,0,0,0")
    return "\n".join(rows) + "\n"


class FakeArchive:
    """data.binance.vision in a dict: path -> bytes; every zip has its .CHECKSUM; anything else is a 404."""

    def __init__(self):
        self.files = {}
        self.asked = []

    def put(self, rel: str, text: str, bad_checksum: bool = False):
        data = _zip(os.path.basename(rel).replace(".zip", ".csv"), text)
        self.files[rel] = data
        h = hashlib.sha256(data).hexdigest() if not bad_checksum else "0" * 64
        self.files[rel + ".CHECKSUM"] = f"{h}  {os.path.basename(rel)}\n".encode()

    def get(self, url: str, timeout: float = 60.0) -> bytes:
        rel = url[len(D.BASE_URL):]
        self.asked.append(rel)
        if rel not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return self.files[rel]


def _world():
    rng = np.random.default_rng(0)
    arc = FakeArchive()
    # January 2020, days 1-4 (the coin then stops: February is a 404): day 2 lacks 30 minutes in the monthly file
    n = 4 * 1440
    ts = JAN + np.arange(n, dtype=np.int64) * MIN
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * 1.0005
    lo = np.minimum(o, c) * 0.9995
    v = rng.uniform(1, 5, n)
    v[100] = 0.0                                          # a minute without trades
    hole = np.arange(1440 + 600, 1440 + 630)              # absent from the monthly file
    keep = np.ones(n, bool)
    keep[hole] = False
    arc.put(D.rel_monthly("klines", SYM, "2020-01"), _klines(ts[keep], o[keep], h[keep], lo[keep], c[keep], v[keep]))
    # the daily file of day 2: every minute, the monthly ones with other values (monthly must win)
    day = slice(1440, 2880)
    arc.put(D.rel_daily("klines", SYM, "2020-01-02"),
            _klines(ts[day], o[day] * 1.01, h[day] * 1.01, lo[day] * 1.01, c[day] * 1.01, v[day], header=False))
    mk = np.ones(n, bool)
    mk[[5, 6]] = False                                    # two minutes without a mark bar
    mk[hole] = False
    arc.put(D.rel_monthly("markPriceKlines", SYM, "2020-01"),
            _klines(ts[mk], o[mk] * 1.001, h[mk] * 1.001, lo[mk] * 1.001, c[mk] * 1.001, np.zeros(mk.sum())))
    arc.put(D.rel_daily("markPriceKlines", SYM, "2020-01-02"),
            _klines(ts[day], o[day] * 1.002, h[day] * 1.002, lo[day] * 1.002, c[day] * 1.002, np.zeros(1440)))
    f_t = JAN + np.arange(0, 4 * DAY, 8 * 3_600_000) + 7       # calc times a few ms past the minute
    arc.put(D.rel_monthly("fundingRate", SYM, "2020-01"),
            "calc_time,funding_interval_hours,last_funding_rate\n" +
            "".join(f"{int(t)},8,{0.0001 * (k + 1)!r}\n" for k, t in enumerate(f_t)))
    return arc, dict(ts=ts, o=o, h=h, l=lo, c=c, v=v, hole=hole, mk=mk, day=day, f_t=f_t)


@pytest.fixture()
def kit(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "MIN_FREE", 0)
    arc, truth = _world()
    d = str(tmp_path / "kit")
    D.download(d, "2020-01", "2020-03", (SYM,), procs=2, get=arc.get)
    rep = D.build(d, "2020-01", "2020-03", (SYM,))
    return d, arc, truth, rep


def test_download_asks_only_for_the_kit_months(kit):
    d, arc, truth, rep = kit
    months = {r.split("-1m-")[-1][:7] if "-1m-" in r else r.split("-fundingRate-")[-1][:7] for r in arc.asked}
    assert months <= {"2020-01", "2020-02", "2020-03"}
    assert any("daily" in r and "2020-01-02" in r for r in arc.asked)
    assert not any("daily" in r and "2020-01-03" in r for r in arc.asked)      # a full day is not re-read
    man = D._manifest(d)
    assert D.rel_monthly("klines", SYM, "2020-02") in man["missing"]
    # a second download asks nothing again (files kept, 404s remembered)
    n = len(arc.asked)
    D.download(d, "2020-01", "2020-03", (SYM,), procs=2, get=arc.get)
    assert all(r.endswith(".CHECKSUM") is False for r in arc.asked[n:]) and len(arc.asked) == n


def test_checksum_mismatch_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    arc = FakeArchive()
    rel = D.rel_monthly("klines", SYM, "2020-01")
    arc.put(rel, _klines([JAN], [1.0], [1.0], [1.0], [1.0], [1.0]), bad_checksum=True)
    with pytest.raises(RuntimeError, match="download failed"):
        D.fetch(str(tmp_path), rel, tries=2, get=arc.get)
    assert not os.path.exists(os.path.join(str(tmp_path), rel))


def test_build_layout_and_rules(kit):
    d, arc, truth, rep = kit
    z = D.load(d, SYM)
    assert set(z) == set(D.ARRAYS)
    ts = truth["ts"]
    assert z["ts"].dtype == np.int64 and all(z[k].dtype == np.float64 for k in D.ARRAYS if k != "ts")
    assert (np.diff(z["ts"]) > 0).all()
    assert ts[100] not in z["ts"]                                   # zero volume dropped
    assert np.isin(ts[truth["hole"]], z["ts"]).all()                 # absent minutes filled from the daily file
    j = np.searchsorted(z["ts"], ts[truth["hole"][0]])
    assert z["o"][j] == truth["o"][truth["hole"][0]] * 1.01         # (daily values there)
    j = np.searchsorted(z["ts"], ts[1500])                           # a day-2 minute the monthly file has
    assert z["o"][j] == truth["o"][1500] and z["mo"][j] == truth["o"][1500] * 1.001     # monthly wins
    j = np.searchsorted(z["ts"], ts[5])
    assert z["mo"][j] == z["o"][j] and z["mh"][j] == z["h"][j]       # missing mark: the last-price bar
    assert abs(z["qv"][j] - truth["v"][5] * truth["c"][5]) < 1e-9
    # funding on the floored calc minute (the minute after it when missing: none here)
    f_idx = np.flatnonzero(z["fund"])
    assert list(z["ts"][f_idx]) == list(truth["f_t"] // MIN * MIN)
    assert abs(z["fund"][f_idx[2]] - 0.0003) < 1e-15
    r = rep["symbols"][0]
    assert r["ended"] and r["zero_volume_dropped"] == 1 and r["mark_filled_from_last"] == 2
    assert r["content_sha256"] == D.content_sha(z)


def test_content_hash_is_the_hunts(tmp_path):
    from research.hunt import data_hunt as DH
    rng = np.random.default_rng(1)
    arrs = {"ts": np.arange(10, dtype=np.int64) * MIN, **{k: rng.random(10) for k in ("o", "h", "l", "c", "v", "qv")}}
    p = str(tmp_path / "x.npz")
    np.savez(p, **arrs)
    assert D.content_sha(arrs, ("ts", "o", "h", "l", "c", "v", "qv"))["all"] == DH.content_sha(p, "5m")
    one = D.content_sha(arrs)["o"]
    assert one == hashlib.sha256("o|<f8|10\n".encode() + arrs["o"].tobytes()).hexdigest()


def test_load_checks_hashes_and_cuts(kit):
    d, arc, truth, rep = kit
    want = rep["symbols"][0]["content_sha256"]
    cut = JAN + 2 * DAY + 37 * MIN
    z = D.load_kit(d, SYM, cut, want)
    assert z["ts"][-1] < cut and z["ts"][-1] == cut - MIN
    assert all(len(z[k]) == len(z["ts"]) for k in z)
    bad = dict(want)
    bad["mh"] = "0" * 64
    with pytest.raises(D.DataMismatch):
        D.load_kit(d, SYM, cut, bad)
    full = D.load_kit(d, SYM)
    assert len(full["ts"]) > len(z["ts"]) and D.coin_ended(full, D.ms("2020-04-01"))
    assert not D.coin_ended(full, int(full["ts"][-1]) + MIN)


def test_two_kits_join_and_overlap_is_refused(tmp_path):
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    for d, t0 in ((a, 0), (b, 100)):
        os.makedirs(os.path.join(d, "1m"))
        ts = (t0 + np.arange(100, dtype=np.int64)) * MIN
        np.savez(os.path.join(d, "1m", "XUSDT.npz"), ts=ts, **{k: ts.astype(float) for k in D.ARRAYS if k != "ts"})
    z = D.load_cut([a, b], "XUSDT", 150 * MIN)
    assert len(z["ts"]) == 150 and (np.diff(z["ts"]) == MIN).all()
    np.savez(os.path.join(b, "1m", "XUSDT.npz"), ts=np.arange(99, 120, dtype=np.int64) * MIN,
             **{k: np.zeros(21) for k in D.ARRAYS if k != "ts"})
    with pytest.raises(D.DataMismatch, match="overlaps"):
        D.load_cut([a, b], "XUSDT", 150 * MIN)


def test_frames_come_from_the_cut_arrays_into_hiwrs_own_folder(tmp_path):
    R = D.fg_run()
    n = 3 * 1440
    ts = JAN + np.arange(n, dtype=np.int64) * MIN
    px = 100 + np.sin(np.arange(n) / 50.0)
    arr = dict(ts=ts, o=px, h=px + 0.1, l=px - 0.1, c=px, v=np.ones(n))
    cut = JAN + 2 * DAY + 90 * MIN
    cutarr = {k: v[ts < cut] for k, v in arr.items()}
    fd = str(tmp_path / "frames_sel")
    fr = D.make_frames(cutarr, SYM, ("15m", "1h", "4h"), fd)
    for tf, (df, close) in fr.items():
        step = R.TF_MS[tf]
        assert close[-1] <= cut and os.path.exists(D.frame_path(fd, SYM, tf))
        want = np.arange(JAN + step, cut + 1, step)                    # complete UTC bins of the cut minutes
        assert (close == want).all()
        last = np.searchsorted(cutarr["ts"], want - MIN)
        assert (df["close"].to_numpy() == cutarr["c"][last]).all()
    assert fr["1h"][1][-1] == JAN + 2 * DAY + 60 * MIN                # the 01:00-02:00 bar is incomplete: dropped
    old_md = R.minute_data
    undo = D.use_frames(fd)
    try:
        df, close = R.frame("hiwr-sel", SYM, "1h")
        assert (close == fr["1h"][1]).all()
        with pytest.raises(RuntimeError, match="not in"):
            R.frame("hiwr-sel", "BBBUSDT", "1h")
    finally:
        undo()
    assert R.minute_data is old_md


def test_cross_checks():
    rng = np.random.default_rng(2)
    n = 3000
    ts = JAN + np.arange(n, dtype=np.int64) * MIN
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    a = dict(ts=ts, o=c.copy(), h=c * 1.001, l=c * 0.999, c=c.copy(), v=rng.uniform(1, 2, n), mo=c.copy(),
             mh=c * 1.001, ml=c * 0.999, mc=c.copy())
    fg = {k: v.copy() for k, v in a.items()}
    res = D.check_fg1m(a, fg, ts[-1] + MIN)
    assert res["pass"] and res["differing"] == 0 and res["common_minutes"] == n
    fg["h"][10] *= 1 + 1e-6
    res = D.check_fg1m(a, fg, ts[-1] + MIN)
    assert res["differing"] == 1 and res["per_array"]["h"] == 1 and not res["pass"]       # 1/3000 > 0.01%
    five = D.resample_5m(a)
    assert len(five["ts"]) == n // 5 and five["h"][0] == a["h"][:5].max() and five["c"][0] == a["c"][4]
    res = D.check_5m(a, {k: five[k].copy() for k in ("ts", "o", "h", "l", "c", "v")}, ts[-1] + MIN)
    assert res["pass"] and res["share"] == 1.0
    h5 = {k: five[k].copy() for k in ("ts", "o", "h", "l", "c", "v")}
    h5["v"][3] *= 1.01
    res = D.check_5m(a, h5, ts[-1] + MIN)
    assert res["matching"] == len(five["ts"]) - 1 and not res["pass"]


def test_symbols_and_periods():
    assert len(D.SYMBOLS) == 30 and D.SYMBOLS[:3] == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert D.OLD_SIX == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
    assert D.PERIODS["SEL"] == (D.ms("2021-01-01"), D.ms("2024-01-01"))
    assert D.KIT_SEL == ("2020-01", "2023-12") and D.months(*D.KIT_SEL)[-1] == "2023-12"
    assert len(D.months(*D.KIT_SEL)) == 48 and len(D.months(*D.KIT_TEST)) == 33


# ------------------------------------------------------------------ fixes after the 2026-10-12 review
def _two_coin_archive():
    """Two universe coins on a fake archive: BTC trades through Feb 2020, ETH lacks a day in January."""
    rng = np.random.default_rng(5)
    arc = FakeArchive()
    for s, k in (("BTCUSDT", 0), ("ETHUSDT", 1)):
        for m, start in (("2020-01", JAN), ("2020-02", D.ms("2020-02-01"))):
            n = (29 if m == "2020-02" else 31) * 1440
            ts = start + np.arange(n, dtype=np.int64) * MIN
            c = 100 * (k + 1) * np.exp(np.cumsum(rng.normal(0, 0.0005, n)))
            o = np.r_[c[0], c[:-1]]
            keep = np.ones(n, bool)
            if s == "ETHUSDT" and m == "2020-01":
                keep[5 * 1440 + 100:5 * 1440 + 160] = False             # a gap day: filled from the daily file
                day = slice(5 * 1440, 6 * 1440)
                arc.put(D.rel_daily("klines", s, "2020-01-06"),
                        _klines(ts[day], o[day], o[day] * 1.001, o[day] * 0.999, c[day], np.ones(1440)))
                arc.put(D.rel_daily("markPriceKlines", s, "2020-01-06"),
                        _klines(ts[day], o[day], o[day] * 1.001, o[day] * 0.999, c[day], np.zeros(1440)))
            arc.put(D.rel_monthly("klines", s, m), _klines(ts[keep], o[keep], o[keep] * 1.001, o[keep] * 0.999,
                                                           c[keep], np.ones(keep.sum())))
            arc.put(D.rel_monthly("markPriceKlines", s, m), _klines(ts, o, o * 1.001, o * 0.999, c, np.zeros(n)))
            f_t = start + np.arange(0, n * MIN, 8 * 3_600_000)
            arc.put(D.rel_monthly("fundingRate", s, m), "calc_time,funding_interval_hours,last_funding_rate\n" +
                    "".join(f"{int(t)},8,0.0001\n" for t in f_t))
    return arc


def test_kit_one_coin_at_a_time_equals_download_and_build(tmp_path, monkeypatch):
    """Section 3's data pin on the development machine: 'kit' (download, build and drop one coin at a time) writes the
    same arrays and the same build.json as download + build of every coin at once; the raw zips are gone."""
    monkeypatch.setattr(D, "MIN_FREE", 0)
    syms = ("BTCUSDT", "ETHUSDT")
    arc = _two_coin_archive()
    a, b = str(tmp_path / "all"), str(tmp_path / "percoin")
    D.download(a, "2020-01", "2020-02", syms, procs=2, get=arc.get)
    ra = D.build(a, "2020-01", "2020-02", syms)
    n0 = len(arc.asked)
    rb = D.kit(b, "2020-01", "2020-02", syms, procs=2, drop=True, get=arc.get)
    asked = arc.asked[n0:]
    assert sum(1 for r in asked if "daily" in r and "ETHUSDT" in r) == 4          # ETH's gap day, once (+ CHECKSUMs)
    assert not any("daily" in r and "BTCUSDT" in r for r in asked)
    for s in syms:
        assert D.content_sha(D.load(a, s)) == D.content_sha(D.load(b, s))
        assert not os.path.exists(os.path.join(b, "raw", "futures", "um", "monthly", "klines", s))
    assert open(os.path.join(a, "build.json")).read() == open(os.path.join(b, "build.json")).read()
    assert ra["problems"] == rb["problems"] == [] and D.manifest(a) == D.manifest(b)


def test_spans_are_checked_against_section_4():
    month = lambda m: D.ms(m + "-15")                                            # noqa: E731
    rows = [{"symbol": "BTCUSDT", "minutes": 10, "last_ms": month("2023-12"), "ended": False},
            {"symbol": "TOMOUSDT", "minutes": 10, "last_ms": D.ms("2023-11-14"), "ended": True}]
    assert D.span_problems(rows, "2020-01", "2023-12", ("BTCUSDT", "TOMOUSDT")) == []
    # a still-listed coin whose last monthly file went missing "ends" early: stop
    bad = [dict(rows[0], last_ms=month("2023-10"), ended=True), rows[1]]
    assert D.span_problems(bad, "2020-01", "2023-12", ("BTCUSDT", "TOMOUSDT"))[0].startswith("BTCUSDT: ends")
    # TOMO ending in another month than section 4 lists; a coin missing from the kit
    assert "section 4 says 2023-11" in D.span_problems([rows[0], dict(rows[1], last_ms=month("2023-09"))],
                                                         "2020-01", "2023-12", ("BTCUSDT", "TOMOUSDT"))[0]
    assert D.span_problems([rows[0]], "2020-01", "2023-12", ("BTCUSDT", "ETHUSDT")) == \
        ["ETHUSDT: no data in the kit 2020-01 .. 2023-12"]
    # the confirm kit: TOMO is not in it, WAVES ends in 2024-06, the others trade through 2026-09
    test_rows = [{"symbol": "WAVESUSDT", "minutes": 5, "last_ms": D.ms("2024-06-11"), "ended": True},
                 {"symbol": "BTCUSDT", "minutes": 5, "last_ms": month("2026-09"), "ended": False}]
    assert D.span_problems(test_rows, *D.KIT_TEST, symbols=("TOMOUSDT", "WAVESUSDT", "BTCUSDT")) == []
    assert D.span_problems({"BTCUSDT": {"minutes": 5, "last_ms": month("2023-12"), "ended": False}},
                           "2020-01", "2023-12", ("BTCUSDT",)) == []
    assert set(D.ENDS) <= set(D.SYMBOLS) and len(D.ENDS) == 8


def test_the_command_line_never_fetches_confirm_months(tmp_path, capsys):
    """Section 3 / 10.6: confirm-period months are fetched only by 'hiwr test' after the picks line."""
    for argv in (["download", "--dir", str(tmp_path), "--first", "2024-01", "--last", "2026-09"],
                 ["all", "--dir", str(tmp_path), "--first", "2023-06", "--last", "2024-01"],
                 ["kit", "--dir", str(tmp_path), "--first", "2024-01", "--last", "2024-02"]):
        assert D.main(argv) == 2
    assert "confirm period" in capsys.readouterr().err
    assert not os.listdir(str(tmp_path))
