// 🧪 보조지표 조합 연구소(앱) — 뉴럴 데스크 AI 모델 4개가 조합 하나씩 맡아 실시간 데모 거래.
//   조합 4개 × 코인 6개 × (15분 30·40·50배 · 30분 30·40·50배 · 1시간 20·30·40·50배) = 칸 240개, 칸마다 따로 가상자금 $1000.
//   진입·청산은 규칙대로(코드) — 모델 기분이 섞이지 않아야 '이 조합·이 값'의 실력이 공정하게 채점된다. 모델은 맡은 조합의 라운드 복기를 쓴다.
//   값: tools/combo-opt.mjs 가 코인별 5년 백테스트로 고른 후보 9개(lib/combo-opt.js). 라운드(기본 24시간)가 끝날 때마다
//   후보를 '5년 점수 + 최근 데이터 백테스트 + 이번 라운드 실시간 성적'으로 다시 순위 → 5라운드 뒤 가장 꾸준했던 값 = 최종 커스텀 최적값.
//   ⭐ 코인별 대표: 코인 × 30·40·50배마다 (조합 4 × 시간봉 3) 중 앞 4년 학습 1위(BEST). '대표만 거래'로 좁힐 수 있음.
//   전부 가상자금(데모). 실주문 경로 없음.
import { candlesFor } from "../nuri-ai/agent.js";
import { brainStream } from "../nuri-ai/engine.js";
import * as CB from "./lib/combos.js";
import { OPT, META, BEST } from "./lib/combo-opt.js";

const KEY = "coin:combolab", ROUNDS = 5, BARS = 1000, SWITCH = 0.02;   // 1000봉 = 뉴럴 엔진과 같은 요청(캐시 공유)
let L = null, busy = false;
const MK = {};   // `${sym}|${tf}` → { last, D, sigs: Map }
const lk = (c, sym, tf, lev) => `${c}|${sym}|${tf}|${lev}`;
const shortMd = m => String(m || "").split("/").pop().replace(/-instruct|-chat/i, "").slice(0, 18);
const KO = Object.fromEntries(CB.COINS.map(([ko, s]) => [s, ko]));
export const LANES = CB.COMBOS.flatMap(c => CB.COINS.flatMap(([, sym]) => CB.TFS.flatMap(tf => CB.LEVS[tf].map(lev => ({ c: c.key, sym, tf, lev, k: lk(c.key, sym, tf, lev) })))));

function blank() { return { on: true, scope: "all", round: 1, t0: Date.now(), roundAt: Date.now(), roundH: 24, own: {}, sel: {}, lanes: {}, trades: [], log: [], reviews: {}, hist: {}, final: null, made: META.made }; }
export function load() {
  if (!L) { try { L = JSON.parse(localStorage.getItem(KEY)) || blank(); } catch (e) { L = blank(); }
    const b = blank(); for (const k of Object.keys(b)) if (L[k] === undefined) L[k] = b[k];
    // 최적값 파일을 새로 만들었으면 후보 목록이 달라짐 → 라운드·선택만 처음부터(거래 기록·보유 포지션은 그대로)
    if (L.made !== META.made) { L.sel = {}; L.hist = {}; L.round = 1; L.roundAt = Date.now(); L.final = null; L.made = META.made;
      L.log.unshift({ t: Date.now(), round: 0, text: "최적값 새로 만듦(레버리지마다 지표 값·노이즈 거르기까지 따로) → 라운드 1부터 · 거래 기록 유지" }); } }
  return L;
}
function save() { try { localStorage.setItem(KEY, JSON.stringify({ ...L, trades: L.trades.slice(0, 400), log: L.log.slice(0, 60) })); } catch (e) {} }
const cands = (c, sym, tf, lev) => OPT?.[sym]?.[tf]?.[c]?.levs?.[lev] || [];
const lane = k => L.lanes[k] || (L.lanes[k] = { n: 0, w: 0, R: 0, pnl: 0, pos: null, lastSig: 0, skip: 0 });
const candOf = x => { const C = cands(x.c, x.sym, x.tf, x.lev); return C[L.sel[x.k] ?? 0] || C[0] || null; };
const isStar = x => { const b = BEST?.[x.sym]?.[x.lev]; return !!b && b.c === x.c && b.tf === x.tf; };   // ⭐ 코인·레버리지별 대표 칸

// 🤝 담당 배정: 연결된 모델 순서대로 조합 하나씩(모델이 4개보다 적으면 돌아가며 둘 이상 맡음). 모델이 빠지면 다시 배정.
function assign(models) {
  const ms = [...new Set(models)].filter(Boolean); let ch = false;
  CB.COMBOS.forEach((c, i) => { const cur = L.own[c.key];
    if (ms.length && (!cur || !ms.includes(cur))) { const used = new Set(Object.values(L.own)); L.own[c.key] = ms.find(m => !used.has(m)) || ms[i % ms.length]; ch = true; }
    if (!ms.length && !cur) { L.own[c.key] = "자체 엔진"; ch = true; } });
  return ch;
}

// 시세: 15분봉(30분봉은 묶어서) · 1시간봉. 마감된 봉만 신호에 쓴다.
async function bars(sym) {
  const g = async tf => (await candlesFor({ market: sym, exchange: "binancef", timeframe: tf }, BARS)).cs;
  const c15 = await g("15"), c60 = await g("60");
  return { "15": c15, "30": CB.agg30(c15), "60": c60 };
}
function market(sym, tf, cs, now) {
  const closed = cs.filter(b => b.t + CB.TF_MS[tf] <= now), k = sym + "|" + tf, last = closed.at(-1)?.t;
  if (!MK[k] || MK[k].last !== last) MK[k] = { last, D: CB.cols(closed), sigs: new Map() };
  return MK[k];
}
function sigOf(M, c, p) { const key = c + "|" + CB.pkey(p); if (!M.sigs.has(key)) M.sigs.set(key, CB.comboDir(M.D, c, p)); return M.sigs.get(key); }

function close(x, P, px, why, now, feed) {
  const s = P.s, R = ((px - P.e) / P.e * P.side - CB.FEE) / (s + CB.FEE), ln = lane(x.k), pnl = +(R * P.risk).toFixed(2);
  ln.n++; if (R > 0) ln.w++; ln.R = +(ln.R + R).toFixed(3); ln.pnl = +(ln.pnl + pnl).toFixed(2); ln.pos = null;
  L.trades.unshift({ k: x.k, c: x.c, sym: x.sym, ko: KO[x.sym], tf: x.tf, lev: x.lev, side: P.side, e: P.e, x: px, R: +R.toFixed(3), pnl, why, t0: P.t, t1: now, round: P.round, cand: P.cand, owner: L.own[x.c] || "" });
  if (Math.abs(R) >= 1.5 || why === "익절") feed?.(`🧪 [${shortMd(L.own[x.c])}] ${CB.COMBO_BY[x.c].ko} ${KO[x.sym]} ${CB.TF_KO[x.tf]} ${x.lev}x ${P.side > 0 ? "롱" : "숏"} ${why} ${R >= 0 ? "+" : ""}${R.toFixed(2)}R`);
}

// 칸 하나: ① 15분봉 고가·저가로 손절·익절(같은 봉이면 손절 먼저) → ② 그 칸 시간봉 마감에서 청산 신호·시간 → ③ 새 신호면 지금 가격으로 진입
// 정렬된 시각 배열(또는 봉 배열)에서 t 보다 뒤인 첫 위치
function first(a, t) { let lo = 0, hi = a.length; const v = i => typeof a[i] === "number" ? a[i] : a[i].t; while (lo < hi) { const m = (lo + hi) >> 1; if (v(m) <= t) lo = m + 1; else hi = m; } return lo; }
function laneStep(x, M, c15, px, now, feed) {
  const cd = candOf(x); if (!cd || !M.D.n) return;
  const ln = lane(x.k), sig = sigOf(M, x.c, cd.p), D = M.D, li = D.n - 1;
  let P = ln.pos;
  // 15분봉 고가·저가로 손절·익절(until 전까지) — 진입한 15분봉은 건너뜀(진입 전 고가·저가일 수 있음), 본절로 옮긴 그 봉의 저가·고가도 안 씀
  const hit15 = until => { for (let q = first(c15, Math.max(P.t15, P.done15 || 0)); q < c15.length; q++) { const b = c15[q]; if (b.t >= until) break;
      if (P.beBar !== b.t && (P.side > 0 ? b.l <= P.sl : b.h >= P.sl)) { close(x, P, P.sl, P.be ? "본절" : "손절", now, feed); return true; }
      if (P.side > 0 ? b.h >= P.tp : b.l <= P.tp) { close(x, P, P.tp, "익절", now, feed); return true; }
      if (!P.be && (P.side > 0 ? b.h - P.e : P.e - b.l) >= P.e * P.s) { P.be = true; P.beBar = b.t; P.sl = P.e * (1 + P.side * CB.FEE); }
      if (b.t + 900e3 <= now) P.done15 = b.t; }
    return false; };
  if (P) {   // 진입 뒤 마감된 이 칸 시간봉을 차례로(앱이 꺼져 있던 동안 놓친 봉 포함): 그 봉 안의 손절·익절 → 봉 마감의 청산 신호·시간
    for (let j = first(D.t, P.lastBar); j < D.n && P; j++) {
      if (hit15(D.t[j] + CB.TF_MS[x.tf])) { P = null; break; }
      P.lastBar = D.t[j]; P.bars = (P.bars || 0) + 1;
      if (cd.x.ex === 1 && sig.dir[j] === -P.side) { close(x, P, D.c[j], "반대신호", now, feed); P = null; }
      else if (cd.x.ex === 2 && sig.A[j] === -P.side) { close(x, P, D.c[j], "추세전환", now, feed); P = null; }
      else if (P.bars >= CB.HOLD) { close(x, P, D.c[j], "시간", now, feed); P = null; }
    }
    if (P && hit15(Infinity)) P = null;   // 진행 중인 봉
    if (P) {   // 지금 가격
      if (P.side > 0 ? px <= P.sl : px >= P.sl) close(x, P, P.sl, P.be ? "본절" : "손절", now, feed);
      else if (P.side > 0 ? px >= P.tp : px <= P.tp) close(x, P, P.tp, "익절", now, feed);
    }
  }
  // 새 신호: 마지막 마감봉에서 두 지표가 같은 방향이 됨 + 그 다음 봉이 아직 진행 중일 때만(늦게 본 신호는 버림)
  if (!ln.pos && li > 0 && D.t[li] > ln.lastSig && CB.isEntry(sig, li) && now < D.t[li] + 2 * CB.TF_MS[x.tf] && (L.scope !== "best" || isStar(x))) {
    ln.lastSig = D.t[li];
    const side = sig.fd[li], s = CB.slFrac(D, li, cd.x.k, x.lev);
    if (s == null) { ln.skip++; return; }   // ATR 손절이 이 레버리지의 손절 상한(청산거리 40%)보다 넓음 → 진입 안 함
    const eq = CB.LANE_EQ + ln.pnl, risk = +(eq * CB.RISK).toFixed(2), notional = Math.min(eq * 3, risk / (s + CB.FEE));
    ln.pos = { side, e: px, s, sl: px * (1 - side * s), tp: px * (1 + side * CB.tpFrac(s, cd.x.rr)), be: false, risk, notional: +notional.toFixed(2), margin: +(notional / x.lev).toFixed(2),
      liq: px * (1 - side * 0.95 / x.lev), t: now, t15: Math.floor(now / 900e3) * 900e3, lastBar: D.t[li], bars: 0, round: L.round, cand: L.sel[x.k] ?? 0 };
  }
}

// 라운드 끝: 칸마다 후보 9개를 다시 채점 → (1~4라운드) 다음 라운드 값 고르기 · (5라운드) 다섯 번 평균이 가장 좋은 값 = 최종
function rescore(now, feed) {
  const r = L.round, changes = [];
  for (const x of LANES) {
    const C = cands(x.c, x.sym, x.tf, x.lev), M = MK[x.sym + "|" + x.tf]; if (!C.length || !M?.D?.n) continue;
    const cur = L.sel[x.k] ?? 0, H = L.hist[x.k] || (L.hist[x.k] = C.map(() => ({ s: 0, k: 0 })));
    const live = L.trades.filter(t => t.k === x.k && t.round === r && t.cand === cur), lm = live.length ? live.reduce((a, t) => a + t.R, 0) / live.length : 0;
    let best = cur, bv = -Infinity, vc = -Infinity;
    C.forEach((cd, i) => {
      const T = CB.simulate(M.D, sigOf(M, x.c, cd.p), cd.x, x.lev), st = CB.stat(T);
      // 건수 가중 합치기: 앞 4년 학습 점수(수백 건) + 최근 봉 백테스트 + 이번 라운드 실시간 — 며칠치 수십 건이 4년치를 뒤집지 못하게(노이즈 쫓기 방지)
      const n0 = Math.max(30, cd.tr.n), nl = i === cur ? live.length : 0, v = (n0 * cd.plat + st.n * st.mean + nl * lm) / (n0 + st.n + nl);
      H[i] = H[i] || { s: 0, k: 0 }; H[i].s += v; H[i].k++;
      if (i === cur) vc = v;
      if (v > bv) { bv = v; best = i; }
    });
    if (best !== cur && bv - vc < SWITCH) best = cur;   // 0.02R 넘게 나아야 바꿈(근소한 차이로 값이 오락가락하지 않게)
    if (r >= ROUNDS) { const mean = h => h?.k ? h.s / h.k : -Infinity; let fi = best, fv = mean(H[best]);   // 최종 = 다섯 번 평균 1위(지금 값보다 0.02R 넘게 나을 때만 바꿈)
      H.forEach((h, i) => { if (mean(h) > fv) { fv = mean(h); fi = i; } }); best = fi !== best && fv - mean(H[best]) >= SWITCH ? fi : best; }
    if (best !== cur) changes.push(x.k);
    L.sel[x.k] = best;
  }
  L.log.unshift({ t: now, round: r, changed: changes.length, text: r >= ROUNDS ? `5라운드 끝 — 칸 ${LANES.length}개 최종 커스텀 최적값 확정(다섯 번 평균 1위) · 바뀐 칸 ${changes.length}개` : `${r}라운드 끝 — 후보 다시 채점(앞 4년 학습 점수 + 최근 ${BARS}봉 백테스트 + 이번 라운드 실시간, 건수만큼 가중) · 값이 바뀐 칸 ${changes.length}개` });
  if (r >= ROUNDS) L.final = { t: now, sel: { ...L.sel } };
  feed?.(`🧪 조합 연구소 ${L.log[0].text}`);
  L.round = Math.min(ROUNDS + 1, r + 1); L.roundAt = now;
}

function comboStat(c, round = null) { const T = L.trades.filter(t => t.c === c && (round == null || t.round === round)), n = T.length, s = T.reduce((a, t) => a + t.R, 0);
  return { n, R: +s.toFixed(2), wr: n ? Math.round(T.filter(t => t.R > 0).length / n * 100) : null, pnl: +T.reduce((a, t) => a + t.pnl, 0).toFixed(2), mean: n ? +(s / n).toFixed(3) : null }; }
// 담당 모델의 라운드 복기(한국어 2~3문장) — 값 선택은 코드가 하고, 모델은 결과를 읽고 다음 라운드 주의점을 남긴다
async function reviewRound(r, feed, tg = {}) {
  for (const C of CB.COMBOS) {
    const m = L.own[C.key], target = tg[m]; if (!m || !target) continue;
    const st = comboStat(C.key, r), by = CB.COINS.map(([ko, sym]) => { const T = L.trades.filter(t => t.c === C.key && t.sym === sym && t.round === r); return `${ko} ${T.length}건 ${T.reduce((a, t) => a + t.R, 0).toFixed(1)}R`; }).join(" · ");
    const bt = CB.COINS.map(([ko, sym]) => { const c = cands(C.key, sym, "60", 20)[L.sel[lk(C.key, sym, "60", 20)] ?? 0]; return c ? `${ko} 검증1년 ${c.ho.mean}R` : ""; }).filter(Boolean).join(" · ");
    let raw = "";
    try { await brainStream({ target, fallback: false, role: "fast", maxTokens: 220, temperature: 0.3, noThink: true, onContent: d => raw += d, onThink: () => {},
      messages: [{ role: "system", content: "너는 코인 선물 데모 데스크에서 보조지표 조합 하나를 맡은 트레이더다. 숫자만 근거로 한국어 2~3문장 복기를 쓴다. 과장 금지, 주문 지시 금지." },
        { role: "user", content: `맡은 조합: ${C.ko} · ${r}라운드 실시간 데모 결과: ${st.n}건 · 합계 ${st.R}R · 승률 ${st.wr ?? "-"}% · 코인별 ${by}\n5년 백테스트(1시간 20배 칸) ${bt}\n이번 라운드에서 무엇이 통했고 무엇이 안 통했는지, 다음 라운드에 볼 점 하나:` }] }); } catch (e) { raw = ""; }
    const text = raw.replace(/<think>[\s\S]*?<\/think>/g, "").trim().slice(0, 300);
    if (text) { (L.reviews[C.key] ||= []).unshift({ r, m, text, t: Date.now() }); L.reviews[C.key] = L.reviews[C.key].slice(0, 6); feed?.(`🧪 [${shortMd(m)}] ${C.ko} ${r}라운드 복기: ${text.slice(0, 90)}`); save(); }
  }
}

// 뉴럴 데스크 tick 에서 30초마다 · models = 연결된 모델 [{id, model}]
export async function cycle({ models = [], feed = null } = {}) {
  load(); if (!L.on || busy || !OPT) return; busy = true;
  const tg = Object.fromEntries(models.map(m => [m.model, m]));
  try {
    if (assign(models.map(m => m.model))) feed?.(`🧪 조합 연구소 담당: ${CB.COMBOS.map(c => `${c.ko}=${shortMd(L.own[c.key])}`).join(" · ")}`);
    const now = Date.now();
    for (const [, sym] of CB.COINS) {
      let B; try { B = await bars(sym); } catch (e) { continue; }
      const c15 = B["15"], px = c15.at(-1)?.c; if (!px) continue;
      for (const tf of CB.TFS) { const M = market(sym, tf, B[tf], now); for (const x of LANES) if (x.sym === sym && x.tf === tf) laneStep(x, M, c15, px, now, feed); }
    }
    if (L.round <= ROUNDS && now >= L.roundAt + L.roundH * 3600e3) { const r = L.round; rescore(now, feed); save(); reviewRound(r, feed, tg).catch(() => {}); }
  } finally { busy = false; save(); }
}

export function setScope(sc) { load(); L.scope = sc === "best" ? "best" : "all"; save(); return L.scope; }   // 대표만: 다른 칸은 새 진입만 멈춤(보유분은 끝까지 관리)
export function setOn(on) { load(); L.on = !!on; save(); return L.on; }
export function setRoundH(h) { load(); L.roundH = Math.max(1, Math.min(168, +h || 24)); save(); return L.roundH; }
export function restartRounds() { load(); L.round = 1; L.roundAt = Date.now(); L.hist = {}; L.final = null; L.sel = {}; L.log.unshift({ t: Date.now(), round: 0, text: "라운드 처음부터(값은 5년 백테스트 1위로 되돌림 · 거래 기록은 유지)" }); save(); }
export function resetLab() { const own = L?.own; L = blank(); if (own) L.own = own; save(); }

// 화면·뉴트론용 요약
export function labState() {
  load(); const now = Date.now(), open = [];
  const combos = CB.COMBOS.map(C => { const st = comboStat(C.key); let pass = 0, luck = 0, tot = 0, op = 0;
    for (const x of LANES) if (x.c === C.key) { const cd = candOf(x); tot++; if (cd?.pass) pass++; if (cd?.pass && !cd.luck) luck++; const P = L.lanes[x.k]?.pos; if (P) { op++; open.push({ ...x, star: isStar(x), ko: KO[x.sym], side: P.side, e: P.e, sl: P.sl, tp: P.tp, be: P.be, t: P.t, owner: L.own[C.key] }); } }
    return { key: C.key, ko: C.ko, owner: L.own[C.key] || "", ownerShort: shortMd(L.own[C.key]), ...st, open: op, pass, passReal: luck, lanes: tot, cur: comboStat(C.key, L.round), reviews: (L.reviews[C.key] || []).slice(0, 2) }; });
  const grid = {};
  for (const x of LANES) { const cd = candOf(x), ln = L.lanes[x.k] || {};
    ((grid[x.c] ||= {})[x.sym] ||= {})[x.tf + "|" + x.lev] = cd ? { star: isStar(x), p: CB.paramText(x.c, cd.p), x: CB.exitText(cd.x), pass: cd.pass, luck: cd.luck, ho: cd.ho, tr: cd.tr, lb: cd.lb, sel: L.sel[x.k] ?? 0, nC: cands(x.c, x.sym, x.tf, x.lev).length, n: ln.n || 0, R: ln.R || 0, pnl: ln.pnl || 0, skip: ln.skip || 0, pos: ln.pos ? { side: ln.pos.side, be: ln.pos.be } : null } : null; }
  // ⭐ 코인 × 30·40·50배 대표 칸(지금 라운드에서 쓰는 값 + 실시간 성적)
  const best = [], bs = { n: 0, R: 0, pnl: 0, open: 0 };
  for (const [ko, sym] of CB.COINS) for (const lev of [30, 40, 50]) { const b = BEST?.[sym]?.[lev]; if (!b) continue;
    const x = LANES.find(z => z.c === b.c && z.sym === sym && z.tf === b.tf && z.lev === lev), cd = x && candOf(x), ln = (x && L.lanes[x.k]) || {}; if (!cd) continue;
    bs.n += ln.n || 0; bs.R += ln.R || 0; bs.pnl += ln.pnl || 0; if (ln.pos) bs.open++;
    best.push({ ko, sym, lev, c: b.c, cko: CB.COMBO_BY[b.c].ko, cshort: CB.COMBO_BY[b.c].short, tf: b.tf, p: CB.paramText(b.c, cd.p), x: CB.exitText(cd.x), cap: +(40 / lev).toFixed(2),
      tr: cd.tr, ho: cd.ho, lb: cd.lb, pass: cd.pass, luck: b.luck || cd.luck, of: b.of, n: ln.n || 0, R: ln.R || 0, pnl: ln.pnl || 0, pos: ln.pos ? { side: ln.pos.side } : null }); }
  return { on: L.on, scope: L.scope, best, bestSum: { ...bs, R: +bs.R.toFixed(2), pnl: +bs.pnl.toFixed(2) }, round: Math.min(L.round, ROUNDS), rounds: ROUNDS, done: !!L.final, roundH: L.roundH, left: Math.max(0, L.roundAt + L.roundH * 3600e3 - now), made: META.made, from: META.from,
    combos, grid, open, trades: L.trades.slice(0, 40), log: L.log.slice(0, 8), tfs: CB.TFS, levs: CB.LEVS, tfKo: CB.TF_KO, coins: CB.COINS, lanes: LANES.length };
}
