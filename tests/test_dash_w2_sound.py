"""Wave 2 live sound + glow (owners 10/05 22:45: the v6 chiptune sounds; 22:28: "간지나게 빛나고 움직이고").

- core/sound.js loads in node (no AudioContext, no document) and is off by default with the night mute off (one tap
  on the speaker then turns it on: startOnTap, tests/test_dash_gaps_b.py);
- it never makes a sound without a real record: no timer sounds by itself, the first ticker / board / rooms answer is
  only a baseline, an unchanged price is silent; real changes map to the owners' motifs exactly (picker v6 notes);
- the continuous layer is throttled (never more than 2 a second, stale changes dropped, one entry per coin);
- DeepSeek and coin-flip records only feed the continuous layer (no motif per account), trades are heard once;
- the controls persist per device through the wrapped storage helper and bad stored values are cleaned;
- the glow helpers glow only on a real change, honour reduced motion / hidden pages and use tokens (no literal colours).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _node(body: str, store: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    pre = ""
    if store is not None:      # a stand-in for the browser's localStorage, installed before the module reads it
        pre = ("const _ls = new Map(Object.entries(" + json.dumps(store) + "));\n"
               "globalThis.localStorage = {getItem: (k) => _ls.has(k) ? _ls.get(k) : null, setItem: (k, v) => _ls.set(k, String(v)),"
               " removeItem: (k) => _ls.delete(k)}; globalThis._ls = _ls;\n")
    script = pre + f"const sound = await import('{core}/sound.js'); const motion = await import('{core}/motion.js');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


_ON = """
const log = [];
sound._test.setSink((kind, a) => log.push({kind, name: a.name || null, fs: a.fs || null, f: a.f || null, src: a.src || null}));
sound.cfg.on = true; sound.cfg.night = false; sound._test.unlock(true);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
"""


def test_loads_without_audio_and_is_off_by_default():
    out = _node("""console.log(JSON.stringify({cfg: sound.cfg, canPlay: sound.canPlay(), waiting: sound.waiting(),
      chip: sound.CHIP, motifs: sound.MOTIFS, pulse: typeof sound.pulse25}));""")
    assert out["cfg"] == {"on": False, "vol": 60, "density": "normal", "night": False}
    assert out["canPlay"] is False and out["waiting"] is False and out["pulse"] == "function"
    # the owners' picker v6 (scratchpad/sounds/sound_picker.html), note for note
    assert out["chip"] == [369.99, 440.0, 493.88, 554.37, 659.26, 739.99, 830.61, 987.77]
    assert out["motifs"] == {
        "c_entry": [[987.77], [], 0.9],
        "c_tp": [[493.88, 659.26, 987.77], [0.08, 0.08], 0.9],
        "c_sl": [[659.26, 440.0], [0.12], 0.8],
        "c_liq": [[987.77, 830.61, 659.26, 493.88, 369.99], [0.055, 0.055, 0.055, 0.055], 0.9],
        "c_meet": [[554.37, 739.99], [0.14], 0.75],
        "c_ms": [[493.88, 622.25, 739.99, 987.77, 1244.5], [0.07, 0.07, 0.07, 0.07], 0.85],
    }


def test_engine_is_the_pickers_chip_and_one_bus():
    src = _read("core", "sound.js")
    # chip(): square or a 25 % pulse, 9 kHz lowpass, 2 ms attack, 90-150 ms decay; chipRun alternates square / pulse
    assert "im[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * 0.25);" in src
    assert "const len = 0.09 + Math.random() * 0.06, peak = Math.max(v * 0.16, 0.0002);" in src
    assert 'lp.type = "lowpass"; lp.frequency.value = 9000;' in src
    assert 'chip(f, v, t, bus_, i % 2 ? "pulse" : "square"); t += gaps[i] || 0.1;' in src
    # ONE output bus: everything goes through master (the volume); nothing connects straight to the speakers but it
    assert src.count("ctx.destination") == 1 and "master.connect(ctx.destination)" in src
    assert "localStorage" not in src and "local.get(KEY" in src and "local.set(KEY" in src
    assert src.count("setInterval(") == 1 and "setInterval(paint, 60000)" in src     # the label only, never a sound


def test_no_sound_without_a_real_event_and_baselines_are_silent():
    out = _node(_ON + """
    await wait(400);
    const idle = log.length;
    // first answers are baselines: ticker, board rows, rooms
    const m0 = sound.priceMoves({BTCUSDT: {c: 100}, ETHUSDT: {c: 10}}, 0);
    const b0 = sound.onBoardChanged({"S1@15m": [1, 1, false, {symbol: "BTCUSDT", side: 1, entry_time: 5}]});
    const r0 = sound.onRooms({rooms: [{room_id: "team:market", last_id: 5, last_kind: "decision"}]});
    const same = sound.priceMoves({BTCUSDT: {c: 100}, ETHUSDT: {c: 10}}, 1000);
    await wait(300);
    console.log(JSON.stringify({idle, m0, b0, r0, same, log}));""")
    assert out["idle"] == 0 and out["m0"] == [] and out["b0"] == [] and out["r0"] == [] and out["same"] == []
    assert out["log"] == []


def test_real_events_map_to_the_owners_motifs():
    out = _node(_ON + """
    sound._test.setKinds({"S3@1h": "strategy"});
    const r = {};
    r.tp = sound.onTrades([{id: 1, account_id: "S1@15m", kind: "strategy", exit_reason: "LOCK", pnl: 12}], 10000);
    r.sl = sound.onTrades([{id: 2, account_id: "S2@15m", kind: "strategy", exit_reason: "SL", pnl: -3}], 20000);
    r.liq = sound.onTrades([{id: 3, account_id: "REEL_H1@5m", kind: "reel", exit_reason: "LIQ", pnl: -50}], 30000);
    r.again = sound.onTrades([{id: 3, account_id: "REEL_H1@5m", kind: "reel", exit_reason: "LIQ", pnl: -50}], 40000);
    sound.onBoardChanged({"S3@1h": [1, 1, false, null]}, 41000);
    r.entry = sound.onBoardChanged({"S3@1h": [1, 1, false, {symbol: "ETHUSDT", side: -1, entry_time: 9}]}, 50000);
    r.still = sound.onBoardChanged({"S3@1h": [1, 1, false, {symbol: "ETHUSDT", side: -1, entry_time: 9}]}, 60000);
    sound.onRooms({rooms: [{room_id: "team:market", last_id: 5, last_kind: "decision"}]}, 61000);
    r.talk = sound.onRooms({rooms: [{room_id: "team:market", last_id: 6, last_kind: "analysis"}]}, 70000);
    r.meet = sound.onRooms({rooms: [{room_id: "team:market", last_id: 7, last_kind: "decision"}]}, 80000);
    r.burst = sound.onTrades([1, 2, 3, 4, 5, 6].map((i) => ({id: 100 + i, account_id: "S" + i + "@15m", kind: "strategy",
      exit_reason: i === 6 ? "LIQ" : "TP", pnl: i === 6 ? -9 : 4})), 90000);
    r.msNo = sound.milestoneOf({restart: {ready: true, day: 11, of: 30, verdict_ts: 7}});
    r.ms10 = sound.milestoneOf({restart: {ready: true, day: 10, of: 30, verdict_ts: 7}});
    r.msV = sound.milestoneOf({restart: {ready: true, day: 30, of: 30, verdict_ts: 7}});
    await wait(700);
    console.log(JSON.stringify({r, names: log.filter((x) => x.name).map((x) => x.name), first: log[0]}));""")
    r = out["r"]
    assert r["tp"] == ["c_tp"] and r["sl"] == ["c_sl"] and r["liq"] == ["c_liq"] and r["again"] == []
    assert r["entry"] == ["c_entry"] and r["still"] == [] and r["talk"] == [] and r["meet"] == ["c_meet"]
    assert r["burst"] == ["c_liq", "c_tp"]                     # a burst = at most two different motifs, rarest first
    assert r["msNo"] is None and r["ms10"] == "d10-7" and r["msV"] == "verdict-7"
    assert out["names"] == ["c_tp", "c_sl", "c_liq", "c_entry", "c_meet", "c_liq", "c_tp"]
    assert out["first"]["fs"] == [493.88, 659.26, 987.77]


def test_deepseek_and_coin_flips_only_feed_the_layer():
    out = _node(_ON + """
    const m = sound.onTrades([{id: 1, account_id: "DS_A@15m", kind: "ds200", exit_reason: "TP", pnl: 5},
      {id: 2, account_id: "RANDOM_1@1h", kind: "random", exit_reason: "SL", pnl: -5}]);
    await wait(2100);
    console.log(JSON.stringify({m, log}));""")
    assert out["m"] == []
    assert len(out["log"]) == 2 and all(x["name"] is None and x["src"] == "fill" for x in out["log"])
    up = [x for x in out["log"] if x["f"] and x["f"] >= 659]
    assert len(up) == 1                                        # the profit = an upper note, the loss = a lower one


def test_price_changes_drive_the_layer_up_high_down_low():
    out = _node(_ON + """
    sound.priceMoves({BTCUSDT: {c: 100}, ETHUSDT: {c: 10}, SOLUSDT: {c: 5}}, 0);
    const mv = sound.priceMoves({BTCUSDT: {c: 101}, ETHUSDT: {c: 9.9}, SOLUSDT: {c: 5}}, 5000);
    const notes = mv.map((x) => sound.beepOf(x));
    console.log(JSON.stringify({mv, notes}));""")
    mv = out["mv"]
    assert [(x["key"], x["dir"]) for x in mv] == [("px:BTCUSDT", 1), ("px:ETHUSDT", -1)]   # SOL did not move: silent
    first = [n.get("f") or n["fs"][0] for n in out["notes"]]         # a single beep or a run: where it starts
    assert first[0] >= 659.26 and first[1] <= 554.37


def test_layer_throttle_and_stale_drop():
    out = _node("""
    const L = sound.makeLayer(() => 0);                        // the fastest density: only the 2-a-second floor holds
    for (let i = 0; i < 12; i++) L.push({key: "k" + i, dir: 1, size: i, at: 0});
    const capped = L.size;
    let played = [], t = 0;
    while (t <= 5000) { const r = L.next(t); if (r && r.item) played.push(t); t += 50; }
    const L2 = sound.makeLayer(() => 1333);
    L2.push({key: "a", dir: 1, size: 1, at: 0}); L2.push({key: "a", dir: -1, size: 2, at: 100});
    const merged = L2.size;
    const old = sound.makeLayer(() => 1333); old.push({key: "x", dir: 1, size: 1, at: 0});
    console.log(JSON.stringify({capped, played, merged, stale: old.next(sound.MAX_AGE_MS + 1)}));""")
    assert out["capped"] == 8 and out["merged"] == 1 and out["stale"] is None
    gaps = [b - a for a, b in zip(out["played"], out["played"][1:])]
    assert out["played"] and min(gaps) >= 500                  # never more than 2 a second


def test_off_hidden_or_night_means_silent():
    out = _node("""
    const log = []; sound._test.setSink((k, a) => log.push(k));
    const t = {id: 1, account_id: "S1@15m", kind: "strategy", exit_reason: "TP", pnl: 3};
    const off = sound.onTrades([t]);
    sound.cfg.on = true;
    const locked = sound.onTrades([{...t, id: 2}]);            // on, but no tap yet: the browser would refuse anyway
    sound._test.unlock(true); sound.cfg.night = true;
    const night = Date.UTC(2026, 9, 5, 16, 30), day = Date.UTC(2026, 9, 5, 3, 0);    // 01:30 KST / 12:00 KST
    console.log(JSON.stringify({off, locked, n1: sound.nightKst(night), n2: sound.nightKst(day),
      atNight: sound.canPlay(night), atDay: sound.canPlay(day), log}));""")
    assert out["off"] == [] and out["locked"] == [] and out["log"] == []
    assert out["n1"] is True and out["n2"] is False and out["atNight"] is False and out["atDay"] is True


def test_controls_persist_per_device_and_are_cleaned():
    out = _node("""
    const before = {...sound.cfg};
    sound.setCfg({vol: 35, density: "busy", night: false, bogus: 1});
    console.log(JSON.stringify({before, after: sound.cfg, stored: JSON.parse(globalThis._ls.get("pb4-sound"))}));""",
                store={"pb4-sound": json.dumps({"on": False, "vol": 400, "density": "loud", "night": True})})
    assert out["before"] == {"on": False, "vol": 100, "density": "normal", "night": True}
    assert out["after"] == out["stored"] == {"on": False, "vol": 35, "density": "busy", "night": False}


def test_glow_helpers_only_on_real_changes():
    out = _node("""
    const el = {textContent: "", dataset: {}};
    const a = motion.tickPrice(el, 100, "100.0", "BTC"), b = motion.tickPrice(el, 100, "100.0", "BTC");
    const c = motion.tickPrice(el, 101, "101.0", "BTC"), d = motion.tickPrice(el, 99, "99.0", "BTC");
    const e = motion.tickPrice(el, 2400, "2,400", "ETH");       // switched coin: a repaint, not a move
    console.log(JSON.stringify({a, b, c, d, e, text: el.textContent}));""")
    assert out == {"a": None, "b": None, "c": "up", "d": "down", "e": None, "text": "2,400"}
    src = _read("core", "motion.js")
    for fn in ("pulseLive", "flashPrice", "fillIn"):
        body = src[src.index(f"export function {fn}("):]
        body = body[: body.index("\n}\n")]
        assert "still()" in body, fn                            # reduced motion and hidden pages: no motion
        assert "setInterval" not in body and "infinite" not in body
    shell = _read("core", "shell.js")
    assert "pulseLive($(\"#hdot\"))" in shell and "ts !== hbTs" in shell     # one pulse per NEW heartbeat only
    assert "soundButton()" in shell and "startSound()" in shell


def test_wave2_styles_use_tokens_only():
    css = _read("components.css")
    part = css[css.index("/* wave 2 glow"):css.index("@media (prefers-reduced-motion: reduce)")]
    part = re.sub(r'url\("data:[^"]*"\)', "", part)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d", part)
    assert "infinite" not in part and "@keyframes" not in part              # static glow, no loop
    tok = _read("tokens.css")
    for k in ("--up-glow", "--down-glow", "--live-glow", "--edge", "--edge-hi", "--edge-glow"):
        assert tok.count(k + ":") == 2, k                       # both skins define it
    for p in (("core", "sound.js"), ("core", "motion.js")):
        src = re.sub(r"^\s*//.*$", "", _read(*p), flags=re.M)
        assert not re.search(r"#[0-9a-fA-F]{6}\b|\brgba?\(\s*\d", src), p


def test_layer_plays_like_the_approved_picker_mix():
    """Owners 10/06 04:00 ("not the sound I liked; that sound, continuously"): the live layer renders each real event
    the way the picker's 한꺼번에 듣기 did: notes vary within the side's register (no one-note-per-coin drone), a third
    of ordinary events are quick runs that mostly rise, singles are sometimes the pulse wave, and the volume is the
    picker's linear bus (60 -> 0.6)."""
    out = _node("""
    let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const N = 3000, notes = [];
    for (let i = 0; i < N; i++) notes.push(sound.beepOf({key: "tk:BTCUSDT", dir: i % 2 ? 1 : -1, size: 1, voice: 1}, rnd));
    const runs = notes.filter((n) => n.fs), singles = notes.filter((n) => n.f);
    const steps = runs.flatMap((n) => n.fs.slice(1).map((f, i) => f > n.fs[i] ? 1 : f < n.fs[i] ? -1 : 0)).filter((d) => d);
    const buyFirst = notes.filter((n, i) => i % 2).map((n) => n.f || n.fs[0]);
    const sellFirst = notes.filter((n, i) => !(i % 2)).map((n) => n.f || n.fs[0]);
    console.log(JSON.stringify({runShare: runs.length / N, pulseShare: singles.filter((n) => n.pulse).length / singles.length,
      upShare: steps.filter((d) => d > 0).length / steps.length, buyNotes: [...new Set(buyFirst)].length,
      sellNotes: [...new Set(sellFirst)].length, buyMin: Math.min(...buyFirst), sellMax: Math.max(...sellFirst),
      maxLen: Math.max(...runs.map((n) => n.fs.length)), inRange: runs.every((n) => n.fs.every((f) => f >= 330 && f <= 1100))}));""")
    assert 0.28 < out["runShare"] < 0.39                       # a third of the stream is a 띠-링 run
    assert 0.24 < out["pulseShare"] < 0.36 and out["upShare"] > 0.6   # pulse 3 in 10; runs mostly climb (some clamp flat)
    assert out["buyNotes"] == 4 and out["sellNotes"] == 4      # every note of the register, not one per coin
    assert out["buyMin"] >= 659.26 and out["sellMax"] <= 554.37 and out["maxLen"] <= 3 and out["inRange"]
    src = open(os.path.join(V4, "core", "sound.js"), encoding="utf-8").read()
    assert "const gainOf = () => cfg.vol / 100;" in src         # the picker's bus: volume 60 = gain 0.6
