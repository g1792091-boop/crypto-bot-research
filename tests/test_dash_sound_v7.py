"""Live sound engine v7 "영상 기계음" (owners 10/06: "기계소리랑 똑같이" — the YouTube stream's machine sounds).

- core/sound7.js holds the measured sounds as plans (no recording is shipped: no audio file, no fetch, no decode):
  the trade notes are triangle waves at the stream's exact pitches (buy E5 G#5 B5 E6, sell B4 G4 F#4 D4 B3), in the
  stream's kinds 띵 (one) / 띠띠 (the same note twice, 85 ms) / 띠링 (two notes, 80 ms) / 띠리리링·띠릭 (runs, the last
  note twice), sells louder than buys and runs louder than single beeps, as measured;
- the size of a real trade picks the kind like the stream (relay buckets 1-2 one, 3 two, 4 a run); two real trades that
  waited together may become one 띠띠 / 겹침 sound (at most one sound in COMBO_EVERY); the queue's spacing rules hold;
- our events use the stream's two alert sounds (반짝 run, 딩딩 mallet) for 진입 / 익절 / 손절 / 강제청산 / 회의 / 기념;
- v7 is the default, v6 (칩튠) stays selectable per device (소리 종류), and the v6 notes are unchanged;
- render7 connects only to the bus it is given (the one master gain), stops every oscillator, no timers.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
CORE = "file://" + os.path.join(V4, "core")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _node(body: str, store: dict | None = None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = ""
    if store is not None:
        pre = ("const _ls = new Map(Object.entries(" + json.dumps(store) + "));\n"
               "globalThis.localStorage = {getItem: (k) => _ls.has(k) ? _ls.get(k) : null, setItem: (k, v) => _ls.set(k, String(v)),"
               " removeItem: (k) => _ls.delete(k)}; globalThis._ls = _ls;\n")
    script = pre + body + "\nprocess.stdout.write(JSON.stringify(out) + '\\n', () => process.exit(0));"
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _mulberry32(seed: int, n: int) -> list:
    """sound7.js noise7() in Python (the offline renderer's copy)."""
    M = 0xFFFFFFFF
    a, out = seed & M, []
    for _ in range(n):
        a = (a + 0x6D2B79F5) & M
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & M
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & M)) & M)) & M
        out.append(((t ^ (t >> 14)) & M) / 4294967296 * 2 - 1)
    return out


def test_trade_kinds_are_the_streams_notes_timing_and_levels():
    out = _node(f"""const m = await import('{CORE}/sound7.js');
    const out = {{note: m.NOTE7, shape: m.SHAPE7, atk: m.ATK7, kinds: {{}}}};
    for (const side of [1, -1]) for (const k of ["one", "dbl", "pair", "run"]) {{
      const p = m.tick7(side, 1, 0.7, k);
      out.kinds[(side > 0 ? "buy-" : "sell-") + k] = {{fs: p.fs || [p.f], at: p.voices.map((x) => x.at), w: [...new Set(p.voices.map((x) => x.w))],
        peaks: p.voices.map((x) => x.peak), kind: p.kind}};
    }}
    out.bySize = [1, 1.3, 1.6, 3].map((s) => m.kindOf7(s));""")
    n = out["note"]
    assert n == {"E5": 659.26, "Gs5": 830.61, "B5": 987.77, "E6": 1318.51, "B4": 493.88, "G4": 392.0, "Fs4": 369.99,
                 "D4": 293.66, "B3": 246.94}                                   # measured in the stream to +-2 cents
    assert out["shape"]["std"] == [[0.64, 0.043], [0.36, 0.24]] and out["atk"] == 0.009
    k = out["kinds"]
    assert all(v["w"] == ["triangle"] for v in k.values())                     # partials -19 / -28 / -34 dB: a triangle
    assert k["buy-one"]["fs"] == [659.26] and k["sell-one"]["fs"] == [493.88]
    assert k["buy-pair"]["fs"] == [659.26, 830.61] and k["sell-pair"]["fs"] == [493.88, 392.0]        # 띠링
    assert k["buy-pair"]["at"] == [0, 0.08] and k["sell-dbl"]["fs"] == [493.88, 493.88] and k["sell-dbl"]["at"] == [0, 0.085]
    assert k["buy-run"]["fs"] == [659.26, 830.61, 987.77, 1318.51, 1318.51]                          # 띠리리링
    assert k["sell-run"]["fs"] == [493.88, 369.99, 293.66, 246.94, 246.94]                           # 띠릭
    assert min(min(v["fs"]) for kk, v in k.items() if kk.startswith("buy")) >= 659.26     # buy = the upper notes
    assert max(max(v["fs"]) for kk, v in k.items() if kk.startswith("sell")) <= 493.88    # sell = the lower notes
    assert k["sell-one"]["peaks"][0] / k["buy-one"]["peaks"][0] == pytest.approx(10 ** (4 / 20), rel=0.02)  # +4 dB
    assert max(k["sell-run"]["peaks"]) > 3 * k["sell-one"]["peaks"][0] and max(k["buy-run"]["peaks"]) > 2.5 * k["buy-one"]["peaks"][0]
    assert out["bySize"] == ["one", "one", "pair", "run"]                       # relay buckets 1, 2, 3, 4


def test_event_sounds_use_the_streams_alert_sounds():
    out = _node(f"""const m = await import('{CORE}/sound7.js');
    const out = {{}};
    for (const n of ["c_entry", "c_tp", "c_sl", "c_liq", "c_meet", "c_ms", "nope"]) {{
      const p = m.motif7(n, 0.8);
      out[n] = p && {{fs: p.fs, n: p.voices.length, w: [...new Set(p.voices.map((x) => x.w))].sort(),
        sum: p.voices.reduce((a, x) => a + x.peak, 0)}};
    }}""")
    assert out["nope"] is None
    assert out["c_tp"]["fs"] == [349.23, 392.0, 523.25, 659.26]                # the stream's sparkle run F4 G4 C5 E5
    assert out["c_sl"]["fs"] == sorted(out["c_sl"]["fs"], reverse=True)         # the same sound falling
    assert out["c_meet"]["fs"] == [1176.7, 1176.7, 1047.5, 1176.7, 989.1]       # the stream's mallet phrase
    assert out["c_entry"]["fs"] == [1176.7, 1176.7]
    assert out["c_liq"]["fs"] == sorted(out["c_liq"]["fs"], reverse=True) and len(out["c_liq"]["fs"]) == 5
    for n in ("c_entry", "c_meet", "c_liq"):
        assert out[n]["w"] == ["noise", "sine"]                                 # struck tone + its click
    assert out["c_tp"]["w"] == ["noise", "sine"] and out["c_ms"]["n"] > out["c_tp"]["n"]


def test_render_uses_only_the_given_bus_and_stops_everything():
    out = _node(f"""const m = await import('{CORE}/sound7.js');
    const log = {{conn: [], started: 0, stopped: [], buffers: 0, bad: 0}};
    const dest = {{id: "master"}};
    const param = () => ({{value: 0, setValueAtTime(v) {{ if (!Number.isFinite(v)) log.bad++; }}, linearRampToValueAtTime(v, t) {{ if (!Number.isFinite(v) || !Number.isFinite(t)) log.bad++; }},
      setTargetAtTime(v, t, c) {{ if (!(c > 0) || !Number.isFinite(t)) log.bad++; }}, exponentialRampToValueAtTime(v) {{ if (!(v > 0)) log.bad++; }}}});
    const node = (kind) => ({{kind, frequency: param(), gain: param(), Q: param(), type: "",
      connect(n) {{ log.conn.push([kind, n === dest ? "master" : n.kind]); return n; }},
      start() {{ log.started++; }}, stop(t) {{ log.stopped.push(t); }}}});
    const c = {{sampleRate: 48000, currentTime: 0, destination: {{id: "speakers"}},
      createOscillator: () => node("osc"), createGain: () => node("gain"), createBiquadFilter: () => node("bq"),
      createBufferSource: () => node("buf"), createBuffer: (ch, n) => {{ log.buffers++; const d = new Float32Array(n); return {{getChannelData: () => d}}; }}}};
    for (const p of [m.tick7(1, 3, 0.9), m.tick7(-1, 3, 0.9), m.tick7(1, 1, 0.6, "dbl"), m.motif7("c_meet", 0.75), m.motif7("c_ms", 0.85)])
      m.render7(c, p, dest, 1);
    const out = {{ends: [...new Set(log.conn.filter((x) => x[1] === "master").map((x) => x[0]))].sort(),
      speakers: log.conn.some((x) => x[1] === undefined), started: log.started, stops: log.stopped.length,
      late: log.stopped.every((t) => t > 1 && t < 6), buffers: log.buffers, bad: log.bad,
      noise: Array.from(m.noise7(4, 7)).map((x) => Math.round(x * 1e6) / 1e6)}};""")
    assert out["ends"] == ["gain"] and out["speakers"] is False                 # everything ends on the given bus
    assert out["started"] == out["stops"] + out["buffers"] and out["late"] and out["bad"] == 0
    assert out["noise"] == pytest.approx(_mulberry32(7, 4), abs=2e-6)       # deterministic: the offline mirror has the same
    src = _read("core", "sound7.js")
    code = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    for bad in ("destination", "setTimeout", "setInterval", "fetch(", "decodeAudioData", "XMLHttpRequest", "Audio(",
                ".mp3", ".wav", ".m4a", "data:audio", "localStorage", "document."):
        assert bad not in code, bad                                             # synthesis only, no recording, no timer


def test_v7_is_the_default_and_v6_stays_selectable_per_device():
    out = _node(f"""const sound = await import('{CORE}/sound.js');
    const log = [];
    sound._test.setSink((kind, a) => log.push({{kind, eng: a.eng || "v6", name: a.name || null, fs: a.fs || (a.f ? [a.f] : null), voices: (a.voices || []).length}}));
    sound.cfg.on = true; sound.cfg.night = false; sound._test.unlock(true);
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const out = {{kind0: sound.soundKind(), engines: sound.ENGINES}};
    sound.onTrades([{{id: 1, account_id: "S1@15m", kind: "strategy", exit_reason: "TP", pnl: 3}}], 1000);
    sound.setKind("v6"); out.kind1 = sound.soundKind(); out.stored = globalThis._ls.get("pb4-snd-kind");
    sound.onTrades([{{id: 2, account_id: "S2@15m", kind: "strategy", exit_reason: "TP", pnl: 3}}], 5000);
    sound.setKind("bogus"); out.kind2 = sound.soundKind();
    sound.setKind("v7");
    await wait(50);
    out.log = log;
    out.v7item = sound.beep7Of({{dir: -1, size: 3}}).fs;
    out.v6item = sound.beepOf({{dir: -1, size: 3}}, () => 0.5).fs;
    out.pace = sound.V7_PACE; out.every = sound.COMBO_EVERY;""", store={})
    assert out["kind0"] == "v7" and out["engines"] == {"v7": "영상 기계음(새)", "v6": "칩튠(이전)"}
    assert out["kind1"] == "v6" and out["stored"] == '"v6"' and out["kind2"] == "v6"   # a bad choice is ignored
    a, b = out["log"]
    assert a["eng"] == "v7" and a["name"] == "c_tp" and a["voices"] > 0 and a["fs"] == [349.23, 392.0, 523.25, 659.26]
    assert b["eng"] == "v6" and b["name"] == "c_tp" and b["fs"] == [493.88, 659.26, 987.77]   # v6 note for note
    assert out["v7item"] == [493.88, 369.99, 293.66, 246.94, 246.94] and out["v6item"][0] <= 554.37
    assert out["pace"] == 0.7 and out["every"] == 5
    stored = _node(f"const sound = await import('{CORE}/sound.js'); const out = {{k: sound.soundKind()}};", store={"pb4-snd-kind": '"zzz"'})
    assert stored["k"] == "v7"                                                  # a junk stored value falls back to v7


def test_v7_layer_plays_real_trades_only_with_the_streams_combos():
    out = _node(f"""const sound = await import('{CORE}/sound.js');
    const log = [];
    sound._test.setSink((kind, a) => log.push({{t: Date.now(), kind: a.kind, fs: a.fs || [a.f], src: a.src}}));
    sound.cfg.on = true; sound.cfg.night = false; sound._test.unlock(true);
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const out = {{}};
    await wait(300); out.idle = log.length;                                     // nothing without a real event
    const d = sound.combo7({{dir: 1, size: 1}}, {{dir: 1, size: 1.3}});
    const c = sound.combo7({{dir: -1, size: 1.6}}, {{dir: 1, size: 1}});
    out.dbl = {{kind: d.kind, fs: d.fs}}; out.combo = {{kind: c.kind, fs: c.fs, at: c.voices.map((x) => x.at)}};
    sound.onTicks({{state: "live", ev: [{{s: "BTCUSDT", side: "buy", b: 1}}, {{s: "ETHUSDT", side: "sell", b: 3}}, {{s: "SOLUSDT", side: "buy", b: 4}}]}});
    await wait(1700);
    out.log = log;""")
    assert out["idle"] == 0
    assert out["dbl"] == {"kind": "dbl", "fs": [659.26, 659.26]}                # two small buys together = 띠띠
    assert out["combo"]["kind"] == "combo" and out["combo"]["fs"] == [493.88, 392.0, 659.26]
    assert out["combo"]["at"] == [0, 0.08, 0.16]                                # the second 160 ms later (겹침)
    log = out["log"]
    assert log and all(x["src"] == "trade" for x in log)
    assert log[0]["kind"] == "run" and log[0]["fs"][0] == 659.26                # the biggest (bucket 4 buy) first
    gaps = [b["t"] - a["t"] for a, b in zip(log, log[1:])]
    assert all(g >= 495 for g in gaps)                                          # the 2-a-second floor still holds


def test_speaker_menu_has_the_engine_choice():
    src = _read("core", "sound.js")
    assert 'h("span", {class: "k"}, "종류"), kindSeg)' in src and "setKind(id)" in src
    assert 'export const ENGINES = {v7: "영상 기계음(새)", v6: "칩튠(이전)"};' in src
    assert 'local.get("snd-kind", "v7")' in src                                # per device, v7 by default
    assert "if (a.eng === \"v7\") render7(c, a, master, c.currentTime + 0.01);" in src   # the one master bus
    assert src.count("ctx.destination") == 1
