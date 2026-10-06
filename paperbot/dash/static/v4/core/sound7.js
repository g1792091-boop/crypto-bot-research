// Live sound engine v7 "영상 기계음" (owners 10/06: "기계소리랑 똑같이"): the machine sounds of the YouTube live stream the
// owners pointed at, rebuilt by synthesis only (no recording is shipped or embedded). Measured from the owners' four
// screen recordings (scratchpad/sound7/analysis.md); three kinds of sound were found in the stream:
//   A  the trade notes (almost all of the stream): a plain TRIANGLE wave (partials 1, 3, 5, 7 at -19, -28, -34 dB, no
//      even ones), ~9 ms linear rise, then a two-part fall (64 % with a 43 ms time constant, 36 % with 240 ms: -11 dB at
//      100 ms, -20 dB at ~320 ms). Buys are the E-major notes E5 659.26 / G#5 830.61 / B5 987.77 / E6 1318.51, sells
//      B4 493.88 / G4 392 / F#4 369.99 / D4 293.66 / B3 246.94, sells 1.5 x (+3.5 dB) louder. One note for an ordinary
//      trade, two (E5 G#5 | B4 G4, 80 ms apart) for a bigger one, four (E5 G#5 B5 E6 | B4 F#4 D4 B3) for the biggest.
//   B  a bright rising "띠리리링" (twice in two minutes): sine notes F4 G4 C5 E5 69.6 ms apart, each ~85 ms long, with a
//      glassy sparkle at 19 x and 21 x the note that sounds again ~100 ms later; E5 rings on.
//   C  a mallet "띵 딩 딩 딩 딩" (twice in two minutes): D6 D6 C6 D6 B5 (1176.7 / 1047.5 / 989.1 Hz) 100-170 ms apart, each
//      a struck tone (fundamental rings ~0.5 s, an inharmonic 4.39 x partial gone in ~35 ms, a 10 x partial, a 230 Hz
//      thump) with a short noisy click 2-11 kHz.
// A sound is a PLAN (a list of voices with exact gain automation); render() turns it into WebAudio nodes on the given
// bus. The same plan is rendered offline (scratchpad/sound7/py/render7.py) and compared with the recordings, so the
// numbers below are the ones that were measured and checked. Pure module: no AudioContext, no DOM, no timers.

export const NOTE7 = {E5: 659.26, Gs5: 830.61, B5: 987.77, E6: 1318.51, B4: 493.88, G4: 392.0, Fs4: 369.99, D4: 293.66, B3: 246.94};
/** the trade notes' decay shapes: parts [share, time constant s] after the 9 ms rise */
export const SHAPE7 = {
  std: [[0.64, 0.043], [0.36, 0.24]],
  short: [[1, 0.078]],                   // the middle notes of the biggest sell (the stream's F#4 / D4)
  long: [[0.6, 0.045], [0.4, 0.5]],      // the last note of the biggest buy / sell
};
export const ATK7 = 0.009;
export const STEP7 = 0.08;               // two / four note runs: 80 ms apart
export const DBL7 = 0.085;               // 띠띠: the same note twice, 85 ms apart (the stream's queued trades)
export const UNIT7 = 0.26;               // a sell beep's peak per unit of loudness v; every level below is x this
/** The stream's kinds (census of 97 s of clean stream audio, analysis.md): [notes, levels x UNIT7, start s, shapes].
 *  one = 띵 (62 % of the events), dbl = 띠띠, pair = 띠링, run = 띠리리링 (buy) / 띠릭 (sell) for the biggest trades;
 *  a run's last note sounds twice, the second louder, as in the stream. Sells are +3.5 dB over buys, runs ~+10 dB. */
export const KINDS7 = {
  buy: {
    one: [["E5"], [0.63], [0], ["std"]],
    dbl: [["E5", "E5"], [0.44, 0.44], [0, DBL7], ["std", "std"]],
    pair: [["E5", "Gs5"], [1.2, 1.2], [0, STEP7], ["std", "std"]],
    run: [["E5", "Gs5", "B5", "E6", "E6"], [0.56, 0.56, 0.56, 1.03, 1.84], [0, 0.08, 0.16, 0.24, 0.325], ["std", "std", "std", "long", "long"]],
  },
  sell: {
    one: [["B4"], [1], [0], ["std"]],
    dbl: [["B4", "B4"], [0.7, 0.7], [0, DBL7], ["std", "std"]],
    pair: [["B4", "G4"], [1.6, 1.43], [0, STEP7], ["std", "std"]],
    run: [["B4", "Fs4", "D4", "B3", "B3"], [0.8, 1.67, 1.67, 1.77, 3.75], [0, 0.08, 0.16, 0.24, 0.315], ["std", "short", "short", "std", "long"]],
  },
};
/** size -> kind: < 1.5 one (relay buckets 1-2), < 2.5 pair (bucket 3), else run (bucket 4). */
export const kindOf7 = (size) => (size >= 2.5 ? "run" : size >= 1.5 ? "pair" : "one");

const tri = (f, at, peak, shape) => ({w: "triangle", f, at, peak, atk: ATK7, parts: SHAPE7[shape]});

/** The layer's trade sound: dir > 0 buy (the upper notes), < 0 sell (the lower). `kind`: one | dbl | pair | run
 *  (default: from the size). f (one note) or fs + gaps (several) for the tests and the label; voices = the plan. */
export function tick7(dir, size, v, kind) {
  const kn = Object.hasOwn(KINDS7.buy, kind || "") ? kind : kindOf7(Number(size) || 1);
  const [names, lv, at, sh] = KINDS7[dir > 0 ? "buy" : "sell"][kn];
  const fs = names.map((n) => NOTE7[n]);
  const voices = fs.map((f, i) => tri(f, at[i], UNIT7 * v * lv[i], sh[i]));
  return fs.length === 1 ? {f: fs[0], v, kind: kn, voices}
    : {fs, gaps: at.slice(1).map((t, i) => Math.round((t - at[i]) * 1000) / 1000), v, kind: kn, voices};
}

// ---------------------------------------------------------------- B: the sparkle run
export const SPARK = {step: 0.0696, atk: 0.018, hold: 0.085, rel: 0.01, echo: 0.1, sAtk: 0.015, sTau: 0.03};
const PITCH = {F4: 349.23, G4: 392.0, C5: 523.25, E5: 659.26, E6: 1318.51, G5: 783.99, A4: 440.0};
/** notes [[f, level re the loudest, sparkle 19x level, 21x level]] -> voices; the last note rings on (tail). */
function sparkRun(notes, peak, step = SPARK.step, tail = 0.15) {
  const out = [];
  notes.forEach(([f, lv, s19, s21], i) => {
    const at = i * step, last = i === notes.length - 1;
    const p = peak * Math.pow(10, lv / 20);
    out.push({w: "sine", f, at, peak: p, atk: SPARK.atk,
      parts: last ? [[0.7, 0.4, SPARK.hold, SPARK.rel], [0.3, 0.4, SPARK.hold, tail]] : [[1, 0.4, SPARK.hold, SPARK.rel]]});
    for (const [m, l] of [[19, s19], [21, s21]]) {
      if (f * m > 18000 || l == null) continue;
      for (const [dt, el] of [[0, 0], [SPARK.echo, -1]]) {
        out.push({w: "sine", f: f * m, at: at + 0.002 + dt, peak: peak * Math.pow(10, (l + el) / 20), atk: SPARK.sAtk, parts: [[1, SPARK.sTau]]});
      }
    }
  });
  return out;
}
const RISE = [[PITCH.F4, -7.8, -19, -22], [PITCH.G4, -17, -23, -26], [PITCH.C5, -2.7, -26, -27], [PITCH.E5, 0, -33, -36]];

// ---------------------------------------------------------------- C: the mallet phrase
export const MALLET = {h4: 4.393, h10: 10.01, thump: 230, atk: 0.004, parts: [[0.55, 0.06], [0.45, 0.3]],
  p4: -5, tau4: 0.015, glide4: 0.025, p10: -26, tau10: 0.05, pth: -20, tauth: 0.017, click: -18, clickTau: 0.003, clickHz: 5000};
const M = {D6: 1176.7, C6: 1047.5, B5: 989.1, G5: 783.99, E5: 659.26, A5: 880.0};
/** strikes [[at s, f, level dB]] -> voices */
function mallet(strikes, peak, seed = 7) {
  const out = [];
  strikes.forEach(([at, f, lv], i) => {
    const p = peak * Math.pow(10, lv / 20), dB = (x) => p * Math.pow(10, x / 20);
    out.push({w: "sine", f, at, peak: p, atk: MALLET.atk, parts: MALLET.parts});
    out.push({w: "sine", f: f * MALLET.h4, at, peak: dB(MALLET.p4), atk: 0.002, parts: [[1, MALLET.tau4]], glide: [MALLET.glide4, 0.012]});
    if (f * MALLET.h10 < 18000) out.push({w: "sine", f: f * MALLET.h10, at, peak: dB(MALLET.p10), atk: 0.002, parts: [[1, MALLET.tau10]]});
    out.push({w: "sine", f: MALLET.thump, at, peak: dB(MALLET.pth), atk: 0.002, parts: [[1, MALLET.tauth]]});
    out.push({w: "noise", at, peak: dB(MALLET.click), dur: 0.02, tau: MALLET.clickTau, bp: MALLET.clickHz, q: 0.7, seed: seed + i});
  });
  return out;
}
const PHRASE = [[0, M.D6, -5], [0.1, M.D6, 0], [0.236, M.C6, -4], [0.376, M.D6, -4.5], [0.545, M.B5, -7]];

/** The event sounds (진입 / 익절 / 손절 / 강제청산 / 회의 결론 / 기념) built from the stream's two alert sounds B and C:
 *  익절 = the stream's rising sparkle exactly, 회의 결론 = the stream's mallet phrase exactly, 진입 = its first two
 *  strikes, 손절 = the sparkle falling, 강제청산 = a fast falling mallet run, 기념 = the sparkle then the phrase's end.
 *  fs / gaps = the notes, for tests and the label. */
export function motif7(name, v) {
  const P = 0.6 * v;                      // the stream's alerts are ~10 dB above its trade notes
  let voices, fs;
  if (name === "c_tp") { voices = sparkRun(RISE, P); fs = RISE.map((n) => n[0]); }
  else if (name === "c_sl") {
    const fall = [[PITCH.E5, 0, -33, -36], [PITCH.C5, -2, -26, -27], [PITCH.G4, -5, -23, -26], [PITCH.F4, -3, -19, -22]];
    voices = sparkRun(fall, P * 0.9, 0.085, 0.2); fs = fall.map((n) => n[0]);
  } else if (name === "c_meet") { voices = mallet(PHRASE, P * 0.85); fs = PHRASE.map((s) => s[1]); }
  else if (name === "c_entry") { const s = PHRASE.slice(0, 2); voices = mallet(s, P * 0.85); fs = s.map((x) => x[1]); }
  else if (name === "c_liq") {
    const s = [[0, M.D6, 0], [0.07, M.C6, -1], [0.14, M.B5, -2], [0.21, M.G5, -2], [0.28, M.E5, -1]];
    voices = mallet(s, P * 0.85, 21); fs = s.map((x) => x[1]);
  } else if (name === "c_ms") {
    const s = [[0.3, M.D6, -2], [0.4, M.D6, 0], [0.57, M.B5, -3]];
    voices = sparkRun(RISE, P).concat(mallet(s, P * 0.8, 31)); fs = RISE.map((n) => n[0]).concat(s.map((x) => x[1]));
  } else return null;
  const starts = [...new Set(voices.filter((x) => x.w !== "noise" && x.f < 2000 && x.parts.length > 0).map((x) => x.at))];
  return {name, fs, gaps: starts.slice(1).map((t, i) => Math.round((t - starts[i]) * 1000) / 1000), v, voices};
}

// ---------------------------------------------------------------- shared: the length of a voice and the noise source
/** seconds until a voice is below -60 dB of its peak */
export function voiceEnd(x) {
  if (x.w === "noise") return x.dur;
  let end = x.atk;
  for (const [, tau, hold, rel] of x.parts) end = Math.max(end, hold ? hold + 6.9 * rel : x.atk + 6.9 * tau);
  return end + 0.01;
}
/** deterministic noise (mulberry32), the same numbers in the offline renderer */
export function noise7(n, seed) {
  let a = seed >>> 0;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    out[i] = ((((t ^ (t >>> 14)) >>> 0) / 4294967296) * 2 - 1);
  }
  return out;
}

/** Plan -> WebAudio nodes on `dest` (the one master bus), starting at context time t0. */
export function render7(c, plan, dest, t0) {
  for (const x of plan.voices) {
    const t = t0 + x.at;
    if (x.w === "noise") {
      const n = Math.max(1, Math.floor(c.sampleRate * x.dur)), buf = c.createBuffer(1, n, c.sampleRate), d = buf.getChannelData(0);
      const r = noise7(n, x.seed);
      for (let i = 0; i < n; i++) d[i] = r[i] * Math.exp(-i / (x.tau * c.sampleRate));
      const src = c.createBufferSource(), bp = c.createBiquadFilter(), g = c.createGain();
      src.buffer = buf; bp.type = "bandpass"; bp.frequency.value = x.bp; bp.Q.value = x.q; g.gain.value = x.peak;
      src.connect(bp).connect(g).connect(dest); src.start(t);
      continue;
    }
    const o = c.createOscillator();
    o.type = x.w;
    if (x.glide) { o.frequency.setValueAtTime(x.f * (1 + x.glide[0]), t); o.frequency.exponentialRampToValueAtTime(x.f, t + x.glide[1]); }
    else o.frequency.value = x.f;
    for (const [share, tau, hold, rel] of x.parts) {
      const g = c.createGain(), p = Math.max(x.peak * share, 1e-5);
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(p, t + x.atk);
      g.gain.setTargetAtTime(0, t + x.atk, tau);
      if (hold) g.gain.setTargetAtTime(0, t + hold, rel);
      o.connect(g).connect(dest);
    }
    o.start(t); o.stop(t + voiceEnd(x));
  }
}
