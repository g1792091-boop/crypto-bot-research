// node --test tests/ghcoin_recorder.test.mjs  (run by tests/test_ghcoin.py)
import test from "node:test";
import assert from "node:assert/strict";
import fs from "fs";
import os from "os";
import path from "path";
import * as R from "../ghcoin/recorder.mjs";

const plan = (state, side, price = 100, d = 2) => ({state, side, why: "x", conf: 50, price, big: 0.3, small: 0.3,
  entry: side ? price : null, sl: side ? price - side * d : null, tp1: side ? price + side * 1.5 * d : null,
  tp2: side ? price + side * 3 * d : null, regime: {label: "추세장"}});
const bar = (t, o, h, l, c) => ({t, o, h, l, c, v: 1});
const T0 = 1_800_000_000_000 - (1_800_000_000_000 % 300e3);

test("a call opens only when the state turns long/short, once per side, with a mirror and its cost", () => {
  const st = R.newState();
  assert.equal(R.onPlan(st, "BTCUSDT", plan("wait", 0), T0).opened.length, 0);
  const o = R.onPlan(st, "BTCUSDT", plan("long", 1), T0 + 300e3);
  assert.equal(o.opened.length, 2);
  const [c, m] = o.opened;
  assert.equal(c.side, 1); assert.equal(m.side, -1); assert.equal(m.of, c.id);
  assert.equal(m.sl, 102); assert.equal(m.tp1, 97);
  assert.ok(Math.abs(c.cost_r - 2 * (R.FEE + R.SLIP) * 100 / 2) < 1e-9);
  // same state again: no new call; long again after wait while one is open: still none
  assert.equal(R.onPlan(st, "BTCUSDT", plan("long", 1), T0 + 600e3).opened.length, 0);
  R.onPlan(st, "BTCUSDT", plan("longWait", 1), T0 + 900e3);
  assert.equal(R.onPlan(st, "BTCUSDT", plan("long", 1), T0 + 1200e3).opened.length, 0);
  // another coin is independent
  assert.equal(R.onPlan(st, "ETHUSDT", plan("short", -1), T0 + 1200e3).opened.length, 2);
});

test("grading follows gradeCall: SL first, TP1 = +1.5R, 24h expiry; net R pays the costs", () => {
  const st = R.newState();
  R.onPlan(st, "BTCUSDT", plan("long", 1), T0);
  // bar touching both SL (98) and TP1 (103): loss for the call; the mirror (short, SL 102, TP 97) also hits SL first
  let done = R.gradeBar(st, "BTCUSDT", bar(T0, 100, 103.5, 97.5, 100));
  assert.deepEqual(done.map(x => [x.mirror ? "m" : "c", x.result, x.r]), [["c", "loss", -1], ["m", "loss", -1]]);
  assert.ok(done[0].net_r < -1);
  const st2 = R.newState();
  R.onPlan(st2, "BTCUSDT", plan("long", 1), T0);
  done = R.gradeBar(st2, "BTCUSDT", bar(T0, 100, 103.2, 99.5, 103));
  assert.deepEqual(done.map(x => [x.result, x.r]), [["win", 1.5], ["loss", -1]]);   // the mirror's SL (102) is touched
  const st3 = R.newState();
  R.onPlan(st3, "BTCUSDT", plan("long", 1), T0);
  for (let k = 0; k < 288; k++) R.gradeBar(st3, "BTCUSDT", bar(T0 + k * 300e3, 100, 100.5, 99.5, 100.4));
  done = R.gradeBar(st3, "BTCUSDT", bar(T0 + 288 * 300e3, 100.4, 100.6, 99.6, 101));
  assert.equal(done.length, 2);
  assert.equal(done[0].result, "expire"); assert.equal(done[0].r, 0.5); assert.equal(done[1].r, -0.5);
});

test("an opposite call flips the open call and its mirror at the plan price", () => {
  const st = R.newState();
  R.onPlan(st, "BTCUSDT", plan("long", 1), T0);
  const o = R.onPlan(st, "BTCUSDT", plan("short", -1, 101), T0 + 600e3);
  assert.deepEqual(o.closed.map(x => [x.mirror ? "m" : "c", x.result, x.r]), [["c", "flip", 0.5], ["m", "flip", -0.5]]);
  assert.equal(o.opened.length, 2);
  assert.equal(st.open.length, 2);
});

test("runOnce on fake bars writes board, state and the call events; errors stay per coin", async () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "ghrec-"));
  let n = 0;
  const gh = {C: {analyzeTF: async (cs) => ({score: 0.4}), planOf: () => (n++ < 6 ? plan("wait", 0) : plan("long", 1))},
              P: {scan: () => [{code: "DBOT", name: "쌍바닥", dir: 1, state: "forming", points: {}}]},
              T: {rating: () => ({all: 0.3, label: "매수"})}};
  const mk = (tf, end) => Array.from({length: 501}, (_, i) => bar(end - (501 - i) * R.TF_MS[tf], 100, 101, 99, 100));
  const fetcher = async (sym, tf, now) => { if (sym === "BCHUSDT") throw new Error("HTTP 418"); return mk(tf, now - 1000); };
  const st = R.newState();
  let b = await R.runOnce(out, gh, st, {}, "abc123", T0, fetcher);
  assert.equal(Object.keys(b.coins).length, 5); assert.match(b.errors.BCHUSDT, /418/);
  assert.equal(b.coins.BTCUSDT.patterns["60"][0].name, "쌍바닥"); assert.equal(b.coins.BTCUSDT.rating["240"].label, "매수");
  b = await R.runOnce(out, gh, st, {}, "abc123", T0 + 300e3, fetcher);
  const lines = fs.readFileSync(path.join(out, "calls.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
  assert.ok(lines.length >= 2 && lines.every(x => x.ev === "open"));
  const saved = JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8"));
  assert.equal(saved.open.length, lines.length);
  assert.equal(JSON.parse(fs.readFileSync(path.join(out, "board.json"), "utf8")).commit, "abc123");
  // the pattern history: one line per coin and closed 1h / 4h bar, never twice for the same bar
  const pats = () => fs.readFileSync(path.join(out, "patterns.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
  const n1 = pats().length;
  assert.equal(n1, 2 * 5 * 2);                                 // two passes on new bars x 5 coins x (1h, 4h)
  const p0 = pats()[0];
  assert.equal(p0.patterns[0].name, "쌍바닥"); assert.equal(p0.rating.label, "매수"); assert.ok(p0.t && p0.close);
  await R.runOnce(out, gh, st, {}, "abc123", T0 + 300e3, fetcher);   // same bars again
  assert.equal(pats().length, n1);
});
