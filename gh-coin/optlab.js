// 🔬 지표 최적화 백테스트(앱) — 원하는 코인·기간으로 직접 돌려 4개 조합의 커스텀 최적값을 뽑고, 🧪 조합 연구소에 적용한다.
//   데이터: 바이낸스 선물 과거 캔들(앱의 중계 apiBase 로, 1500개씩 · 0.35초 간격 · 한도 걸리면 기다림) → IndexedDB 에 보관(받은 구간은 다시 안 받음).
//   계산: lib/comboopt.js (tools/combo-opt.mjs 와 같은 함수) 를 Web Worker 에서 — 화면이 멈추지 않음. 워커를 못 쓰면 화면에서 조금씩.
//   구간: 고른 기간을 같은 길이 5구간으로 → 앞 4구간으로 고르고 마지막 1구간(고를 때 안 봄)으로 검증.
//   전부 데모용 값. 실주문 경로 없음.
import { apiBase, idb } from "../nuri-ai/engine.js";
import * as CB from "./lib/combos.js";
import * as OPTM from "./lib/comboopt.js";
import * as LAB from "./combolab.js";

const IV = { "15m": 900e3, "1h": 3600e3 }, WARM = 300, RKEY = "coin:optruns", MAX_RUNS = 15;   // 지표 예열: 시작보다 300봉 앞부터 받음(검증 구간 계산에는 안 들어감)
const sleep = ms => new Promise(r => setTimeout(r, ms));
export const normSym = s => { let x = String(s || "").trim().toUpperCase().replace(/[^A-Z0-9]/g, ""); if (!x) return ""; if (!/USDT$/.test(x)) x += "USDT"; return x; };
export const koOf = sym => sym.replace(/USDT$/, "");
const UI = { stop: false, W: null };   // 창에서 돌린 실행의 중지 표시 — 손실 자동 재최적화(combolab)는 자기 ctx 를 따로 넘겨 서로 안 막음

// ── 캔들 받기 + 캐시 ──
async function fetchPart(sym, iv, a, b, onReq, ctx) {
  const step = IV[iv], out = []; let t = a;
  while (t <= b) {
    if (ctx?.stop) throw new Error("중지함");
    let rows = null;
    for (let k = 0; k < 5 && !rows; k++) {
      let r; try { r = await fetch(`${apiBase("binancef")}/fapi/v1/klines?symbol=${sym}&interval=${iv}&limit=1500&startTime=${Math.floor(t)}&endTime=${Math.floor(b)}`); } catch (e) { await sleep(1500); continue; }
      if (r.status === 429 || r.status === 418) { onReq?.(0, "바이낸스 요청 한도 — 60초 기다림"); await sleep(60e3); continue; }
      if (r.status === 400) { let m = ""; try { m = (await r.json()).msg || ""; } catch (e) {} throw new Error(`바이낸스 선물에 ${sym} 이(가) 없습니다${m ? " (" + m + ")" : ""}`); }
      if (!r.ok) { await sleep(1500); continue; }
      rows = await r.json();
    }
    if (!Array.isArray(rows)) throw new Error("캔들을 받지 못했습니다(네트워크)");
    if (!rows.length) break;
    for (const k of rows) out.push([+k[0], +k[1], +k[2], +k[3], +k[4], +k[5]]);
    onReq?.(1, ""); t = rows.at(-1)[0] + step;
    if (rows.length < 1500) break;
    await sleep(350);
  }
  return out;
}
const toCols = rows => { const n = rows.length, C = { t: new Float64Array(n), o: new Float64Array(n), h: new Float64Array(n), l: new Float64Array(n), c: new Float64Array(n), v: new Float64Array(n) };
  rows.forEach((r, i) => { C.t[i] = r[0]; C.o[i] = r[1]; C.h[i] = r[2]; C.l[i] = r[3]; C.c[i] = r[4]; C.v[i] = r[5]; }); return C; };
const colRows = (C, a = 0, b = C.t.length) => { const out = []; for (let i = a; i < b; i++) out.push([C.t[i], C.o[i], C.h[i], C.l[i], C.c[i], C.v[i]]); return out; };
const sliceCols = (C, from, to) => { let a = 0, b = C.t.length; while (a < b && C.t[a] < from) a++; while (b > a && C.t[b - 1] > to) b--; const o = {}; for (const k of ["t", "o", "h", "l", "c", "v"]) o[k] = C[k].slice(a, b); return o; };
export const reqEstimate = (from, to, iv) => Math.ceil((to - from) / IV[iv] / 1500);

export async function klines(sym, iv, from, to, onProg = null, ctx = null) {
  const step = IV[iv], ck = `optk:${sym}:${iv}|`, now = Date.now();
  let C = null; try { C = (await idb.all(ck))[0] || null; } catch (e) {}
  const parts = [];
  if (!C) parts.push([from, to]);
  else { if (from < C.from) parts.push([from, C.from - 1]); if (to > C.to + step) parts.push([C.to + step, to]); }
  const need = parts.reduce((a, [x, y]) => a + Math.max(1, Math.ceil((y - x) / step / 1500)), 0); let got = 0;
  const onReq = (n, msg) => { got += n; onProg?.(need ? Math.min(1, got / need) : 1, msg || `${iv} 캔들 받는 중 ${got}/${need}`); };
  if (parts.length) {
    const before = [], after = [];
    for (const [x, y] of parts) { const rows = await fetchPart(sym, iv, x, y, onReq, ctx); (C && x < C.from ? before : after).push(...rows); }
    let rows = [...before, ...(C ? colRows(C) : []), ...after].sort((p, q) => p[0] - q[0]);
    rows = rows.filter((r, i) => i === 0 || r[0] !== rows[i - 1][0]).filter(r => r[0] + step <= now);   // 중복 제거 · 아직 안 끝난 봉 제외
    const cols = toCols(rows);
    C = { from: Math.min(from, C?.from ?? from), to: rows.length ? rows.at(-1)[0] : (C?.to ?? from), ...cols };
    try { await idb.put(ck, C); } catch (e) {}
  } else onProg?.(1, `${iv} 캔들: 저장된 것 사용`);
  return sliceCols(C, from, to);
}

// ── 실행 ──
// q = { sym, start, end, tfs: ["15","30","60"], levs: [20,30,40,50], combos: ["st_roc",…] }
export async function run(q, onProg = () => {}, ctx = UI) {
  ctx.stop = false;
  const sym = normSym(q.sym), now = Date.now(), end = Math.min(+q.end || now, now); let start = +q.start;
  const tfs = CB.TFS.filter(t => (q.tfs || []).includes(t)), levs = [20, 30, 40, 50].filter(l => (q.levs || []).includes(l)), combos = CB.COMBOS.map(c => c.key).filter(k => (q.combos || []).includes(k));
  if (!sym) throw new Error("코인을 입력하세요");
  if (!(end - start >= 14 * 864e5)) throw new Error("기간이 너무 짧습니다(최소 14일)");
  if (!tfs.length || !levs.length || !combos.length) throw new Error("시간봉·레버리지·조합을 하나 이상 고르세요");
  if (!tfs.some(tf => CB.LEVS[tf].some(l => levs.includes(l)))) throw new Error("고른 시간봉에 맞는 레버리지가 없습니다(20배는 1시간봉만)");
  const t0 = Date.now(), need15 = tfs.includes("15") || tfs.includes("30"), need60 = tfs.includes("60");
  const k15 = need15 ? await klines(sym, "15m", start - WARM * 1800e3, end, (f, m) => onProg({ phase: "down", f: need60 ? f * 0.8 : f, msg: m }), ctx) : null;
  const k60 = need60 ? await klines(sym, "1h", start - WARM * 3600e3, end, (f, m) => onProg({ phase: "down", f: need15 ? 0.8 + f * 0.2 : f, msg: m }), ctx) : null;
  // 상장이 기간 시작보다 늦으면 시작을 (첫 봉 + 예열)로 미룬다
  // (요청한 첫 봉보다 2봉 넘게 늦게 시작하면 = 그 뒤 상장 · 15분 단위 반올림 차이는 무시)
  const from15 = start - WARM * 1800e3, from60 = start - WARM * 3600e3, late = (k15 && k15.t[0] > from15 + 2 * 900e3) || (k60 && k60.t[0] > from60 + 2 * 3600e3);
  const first = Math.max(k15?.t[0] ?? 0, k60?.t[0] ?? 0), warmEnd = Math.max(k15 ? (k15.t[0] ?? 0) + WARM * 1800e3 : 0, k60 ? (k60.t[0] ?? 0) + WARM * 3600e3 : 0);
  let note = ""; if (late && warmEnd > start) { note = `상장(${new Date(first).toISOString().slice(0, 10)}) 뒤 예열 때문에 시작을 ${new Date(warmEnd).toISOString().slice(0, 10)} 로 미룸`; start = warmEnd; }
  if (!(end - start >= 14 * 864e5)) throw new Error("이 코인은 고른 기간에 캔들이 너무 적습니다(상장 전)");
  const { B, span } = OPTM.foldBounds(start, end, 5);
  const days = (end - start) / 864e5, minN = days >= 365 ? 30 : Math.max(10, Math.round(30 * days / 365));   // 짧은 기간 = 학습 최소 거래 수를 비례로(10 이상)
  if (minN < 30) note = (note ? note + " · " : "") + `기간이 1년보다 짧아 학습 최소 거래 수를 ${minN}건으로 낮춤(결과가 더 흔들림)`;
  const opt = { sym, ko: koOf(sym), B, span, levs, combos, bestLevs: levs, minN };
  onProg({ phase: "calc", f: 0, msg: "계산 시작" });
  const res = await compute({ k15, k60, tfs, opt }, onProg, ctx);
  const out = { id: Date.now().toString(36), sym, ko: koOf(sym), start, end, tfs, levs, combos, made: new Date().toISOString(), span, B: B.slice(0, 5), note, bars: res.bars, ms: Date.now() - t0, auto: q.auto ? String(q.auto) : "", ...res.r };
  await saveRun(out);
  return out;
}
function compute(msg, onProg, ctx) {
  return new Promise((resolve, reject) => {
    let w = null;
    try { w = new Worker(new URL("./lib/optworker.js", import.meta.url), { type: "module" }); } catch (e) { w = null; }
    if (!w) {   // 워커를 못 쓰면 화면에서(조금씩 쉬면서)
      (async () => { const rows = c => Array.from(c.t, (t, i) => ({ t, o: c.o[i], h: c.h[i], l: c.l[i], c: c.c[i], v: c.v[i] })), d = {};
        if (msg.k15) { const c15 = rows(msg.k15); if (msg.tfs.includes("15")) d["15"] = c15; if (msg.tfs.includes("30")) d["30"] = CB.agg30(c15); }
        if (msg.k60 && msg.tfs.includes("60")) d["60"] = rows(msg.k60);
        const r = await OPTM.optimizeCoin({ ...msg.opt, tfs: msg.tfs, data: d, tick: async (f, m) => { if (ctx.stop) throw new Error("중지함"); onProg({ phase: "calc", f, msg: m + " (화면 계산)" }); await sleep(0); } });
        return { r, bars: Object.fromEntries(Object.entries(d).map(([k, v]) => [k, v.length])) }; })().then(resolve, reject);
      return;
    }
    ctx.W = { w, reject };
    w.onmessage = ev => { const m = ev.data;
      if (m.type === "prog") onProg({ phase: "calc", f: m.f, msg: m.msg });
      else if (m.type === "done") { w.terminate(); ctx.W = null; resolve({ r: m.r, bars: m.bars }); }
      else if (m.type === "err") { w.terminate(); ctx.W = null; reject(new Error(m.msg)); } };
    w.onerror = e => { w.terminate(); ctx.W = null; reject(new Error("계산 작업자 오류: " + (e.message || "알 수 없음"))); };
    w.postMessage(msg);
  });
}
export function stop(ctx = UI) { ctx.stop = true; if (ctx.W) { ctx.W.w.terminate(); ctx.W.reject(new Error("중지함")); ctx.W = null; } }

// ── 실행 기록 (전체는 IndexedDB, 목록은 localStorage) ──
const runMeta = r => { const s = r.summary || []; return { id: r.id, auto: r.auto || "", sym: r.sym, ko: r.ko, start: r.start, end: r.end, tfs: r.tfs, levs: r.levs, combos: r.combos, made: r.made, ms: r.ms, n: s.length, pass: s.filter(x => x.pass).length, real: s.filter(x => x.pass && !x.luck).length }; };
export function runs() { try { return JSON.parse(localStorage.getItem(RKEY)) || []; } catch (e) { return []; } }
async function saveRun(r) {
  try { await idb.put("optrun:" + r.id, r); } catch (e) {}
  const L = [runMeta(r), ...runs().filter(x => x.id !== r.id)];
  for (const x of L.slice(MAX_RUNS)) { try { await idb.del("optrun:" + x.id); } catch (e) {} }
  try { localStorage.setItem(RKEY, JSON.stringify(L.slice(0, MAX_RUNS))); } catch (e) {}
}
export async function loadRun(id) { try { return (await idb.all("optrun:" + id))[0] || null; } catch (e) { return null; } }
export async function deleteRun(id) { try { await idb.del("optrun:" + id); } catch (e) {} try { localStorage.setItem(RKEY, JSON.stringify(runs().filter(x => x.id !== id))); } catch (e) {} }

// ── 연구소에 적용 / 해제 ──
export const apply = r => LAB.applyCustom(r);
export const unapply = sym => LAB.removeCustom(sym);
export const applied = () => LAB.customList();

// ── 내보내기 ──
export function csv(r) {
  const head = ["코인", "시간봉", "레버리지", "조합", "지표 값", "손절·익절·청산", "학습 평균R", "학습 건수", "검증 평균R", "검증 건수", "검증 승률%", "통과", "운 범위", "구간1", "구간2", "구간3", "구간4", "구간5(검증)"];
  const lines = [head.join(",")];
  for (const tf of Object.keys(r.out)) for (const c of Object.keys(r.out[tf])) for (const [lev, cs] of Object.entries(r.out[tf][c].levs)) { const x = cs[0]; if (!x) continue;
    lines.push([r.ko, CB.TF_KO[tf], lev + "x", CB.COMBO_BY[c].ko, CB.paramText(c, x.p), CB.exitText(x.x), x.tr.mean, x.tr.n, x.ho.mean, x.ho.n, x.ho.wr, x.pass ? "O" : "X", x.luck ? "O" : "X", ...x.yr.map(y => `${y[1]}(${y[0]})`)].map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")); }
  return "﻿" + lines.join("\n");
}
