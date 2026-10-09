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
// 🔬 직접 최적화 값(optlab.js '지표 최적화 백테스트' 창에서 적용): 그 코인은 기본 5년 값 대신 이 값. 6코인 밖 코인이면 칸이 새로 생김.
const CKEY = "coin:combolab:custom", BASE = new Set(CB.COINS.map(c => c[1]));
let CUST = null, _lanes = null, _lk = "";
function cust() { if (!CUST) { try { CUST = JSON.parse(localStorage.getItem(CKEY)) || {}; } catch (e) { CUST = {}; } } return CUST; }
function saveCust() { localStorage.setItem(CKEY, JSON.stringify(CUST)); }   // 저장 공간이 모자라면 오류를 그대로 올림(화면에 표시)
export const coinsAll = () => [...CB.COINS, ...Object.entries(cust()).filter(([s]) => !BASE.has(s)).map(([s, u]) => [u.ko || s.replace(/USDT$/, ""), s])];
const koOf = sym => (coinsAll().find(c => c[1] === sym) || [sym.replace(/USDT$/, "")])[0];
export function lanesAll() { const cs = coinsAll(), key = cs.map(c => c[1]).join(","); if (_lanes && _lk === key) return _lanes; _lk = key;
  return (_lanes = CB.COMBOS.flatMap(c => cs.flatMap(([, sym]) => CB.TFS.flatMap(tf => CB.LEVS[tf].map(lev => ({ c: c.key, sym, tf, lev, k: lk(c.key, sym, tf, lev) })))))); }
const day = t => new Date(t).toISOString().slice(0, 10);

function blank() { return { on: true, scope: "all", ev: [], auto: { on: true, q: [], log: [], cool: {}, day: "", nDay: 0 }, round: 1, t0: Date.now(), roundAt: Date.now(), roundH: 24, own: {}, sel: {}, lanes: {}, trades: [], log: [], reviews: {}, hist: {}, final: null, made: META.made }; }
export function load() {
  if (!L) { try { L = JSON.parse(localStorage.getItem(KEY)) || blank(); } catch (e) { L = blank(); }
    const b = blank(); for (const k of Object.keys(b)) if (L[k] === undefined) L[k] = b[k];
    L.auto = { ...b.auto, ...(L.auto || {}) }; if (!Array.isArray(L.ev)) L.ev = [];
    // 최적값 파일을 새로 만들었으면 후보 목록이 달라짐 → 라운드·선택만 처음부터(거래 기록·보유 포지션은 그대로)
    if (L.made !== META.made) { L.sel = {}; L.hist = {}; L.round = 1; L.roundAt = Date.now(); L.final = null; L.made = META.made;
      L.log.unshift({ t: Date.now(), round: 0, text: "최적값 새로 만듦(레버리지마다 지표 값·노이즈 거르기까지 따로) → 라운드 1부터 · 거래 기록 유지" }); } }
  return L;
}
function save() { try { localStorage.setItem(KEY, JSON.stringify({ ...L, trades: L.trades.slice(0, 400), log: L.log.slice(0, 60), ev: (L.ev || []).slice(0, 150), auto: { ...L.auto, log: (L.auto?.log || []).slice(0, 30) } })); } catch (e) {} }
const cands = (c, sym, tf, lev) => { const u = cust()[sym], a = u?.out?.[tf]?.[c]?.levs?.[lev]; if (a) return a; return u && !BASE.has(sym) ? [] : OPT?.[sym]?.[tf]?.[c]?.levs?.[lev] || []; };
const isCustom = x => !!cust()[x.sym]?.out?.[x.tf]?.[x.c]?.levs?.[x.lev];
const bestOf = (sym, lev) => cust()[sym]?.best?.[lev] || (BASE.has(sym) ? BEST?.[sym]?.[lev] : null);
const lane = k => L.lanes[k] || (L.lanes[k] = { n: 0, w: 0, R: 0, pnl: 0, pos: null, lastSig: 0, skip: 0 });
const candOf = x => { const C = cands(x.c, x.sym, x.tf, x.lev); return C[L.sel[x.k] ?? 0] || C[0] || null; };
const isStar = x => { const b = bestOf(x.sym, x.lev); return !!b && b.c === x.c && b.tf === x.tf; };   // ⭐ 코인·레버리지별 대표 칸

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
  L.trades.unshift({ k: x.k, c: x.c, sym: x.sym, ko: koOf(x.sym), tf: x.tf, lev: x.lev, side: P.side, e: P.e, x: px, R: +R.toFixed(3), pnl, why, t0: P.t, t1: now, round: P.round, cand: P.cand, owner: L.own[x.c] || "" });
  const ev = { t: now, ty: "x", k: x.k, c: x.c, ko: koOf(x.sym), tf: x.tf, lev: x.lev, side: P.side, e: P.e, x: px, R: +R.toFixed(2), pnl, why, owner: L.own[x.c] || "" };
  L.ev.unshift(ev); if (CY) CY.exits.push(ev); else feed?.(`🧪 청산 ${CB.COMBO_BY[x.c].short} ${ev.ko} ${CB.TF_KO[x.tf]} ${x.lev}배 ${why} ${sg(ev.R)}R`);
  autoCheck(x, ln, now);
}
const sg = v => `${v >= 0 ? "+" : ""}${v}`, fmtP = v => v >= 1000 ? Math.round(v).toLocaleString() : v >= 1 ? (+v).toFixed(2) : (+v).toPrecision(4);
let CY = null;   // 이번 주기에 생긴 진입·청산(같은 신호의 30·40·50배를 한 줄로 알리려고 모음)

// 🔧 손실 자동 재최적화 — 칸이 3연속 손실이거나 값을 정한 뒤 합계 −3R 이하면 → 그 코인 최근 1년으로 그 칸들의 커스텀 값을 다시 찾음(백그라운드)
//   새 값이 '고를 때 안 본 마지막 구간'에서도 플러스(통과)인 칸만 바꾸고, 아니면 기존 값 유지. 코인마다 12시간 쿨다운 · 하루 8번까지.
const AUTO = { streak: 3, sum: -3, coolH: 12, perDay: 8, days: 365 }, AUTO_CTX = { stop: false, W: null };
let autoRun = null;
function autoLog(text, id = "") { (L.auto.log ||= []).unshift({ t: Date.now(), text, id }); }
function autoCheck(x, ln, now) {
  const A = L.auto; if (!A?.on) return;
  const T = L.trades.filter(t => t.k === x.k && t.t1 >= (ln.since || 0)); let st = 0; for (const t of T) { if (t.R < -0.05) st++; else break; }
  const sum = T.reduce((a, t) => a + t.R, 0); if (st < AUTO.streak && sum > AUTO.sum) return;
  if (A.q.some(q => q.k === x.k)) return;
  const why = st >= AUTO.streak ? `${st}연속 손실` : `값 정한 뒤 합계 ${sum.toFixed(1)}R`;
  A.q.push({ k: x.k, c: x.c, sym: x.sym, tf: x.tf, lev: x.lev, why, t: now });
  autoLog(`⏳ ${koOf(x.sym)} ${CB.TF_KO[x.tf]} ${x.lev}배 ${CB.COMBO_BY[x.c].short} — ${why} → 재최적화 대기${A.cool[x.sym] > now ? `(쿨다운 ${Math.ceil((A.cool[x.sym] - now) / 3600e3)}시간 남음)` : ""}`);
}
function setLane(sym, q, C, r) {   // 칸 하나만 새 후보로(그 코인의 다른 칸은 그대로)
  const u = cust()[sym] || (CUST[sym] = { id: r.id, sym, ko: r.ko, start: r.start, end: r.end, made: r.made, span: r.span, tfs: [], levs: [], combos: [], out: {}, best: {}, at: Date.now(), auto: true });
  ((u.out[q.tf] ||= {})[q.c] ||= { levs: {}, K: r.out[q.tf][q.c].K }).levs[q.lev] = C;
  (u.meta ||= {})[q.tf + "|" + q.c + "|" + q.lev] = { start: r.start, end: r.end, span: r.span, at: Date.now(), id: r.id, auto: 1 };
  delete L.sel[q.k]; delete L.hist[q.k];
  try { saveCust(); } catch (e) {}
}
async function autoStep(feed) {
  const A = L.auto; if (!A?.on || autoRun || !A.q.length) return;
  const now = Date.now(), d = day(now); if (A.day !== d) { A.day = d; A.nDay = 0; }
  const q0 = A.q.find(q => !(A.cool[q.sym] > now)); if (!q0 || A.nDay >= AUTO.perDay) return;
  const sym = q0.sym, lanesQ = A.q.filter(q => q.sym === sym); A.q = A.q.filter(q => q.sym !== sym);
  const tfs = [...new Set(lanesQ.map(q => q.tf))], levs = [...new Set(lanesQ.map(q => q.lev))], combos = [...new Set(lanesQ.map(q => q.c))];
  A.nDay++; A.cool[sym] = now + AUTO.coolH * 3600e3;
  autoRun = { sym, ko: koOf(sym), f: 0, msg: "시작", n: lanesQ.length, t: now }; save();
  const nm = q => `${CB.TF_KO[q.tf]} ${q.lev}배 ${CB.COMBO_BY[q.c].short}`;
  feed?.(`🔧 손실 자동 재최적화 시작: ${koOf(sym)} ${lanesQ.map(q => `${nm(q)}(${q.why})`).join(", ")} — 최근 1년으로 커스텀 값 다시 찾기`);
  try {
    const OL = await import("./optlab.js");
    const r = await OL.run({ sym, start: now - AUTO.days * 864e5, end: now, tfs, levs, combos, auto: lanesQ.map(q => q.why).join(",") },
      p => { if (autoRun) { autoRun.f = p.phase === "down" ? p.f * 0.25 : 0.25 + p.f * 0.75; autoRun.msg = p.msg; } }, AUTO_CTX);
    const res = []; let ch = 0;
    for (const q of lanesQ) { const C = r.out?.[q.tf]?.[q.c]?.levs?.[q.lev], nb = C?.[0];
      lane(q.k).since = Date.now();
      if (nb && nb.pass) { setLane(sym, q, C, r); ch++; res.push(`✅ ${nm(q)}: 새 값 ${CB.paramText(q.c, nb.p)} · ${CB.exitText(nb.x)} (검증 ${sg(nb.ho.mean)}R/${nb.ho.n}건)`); }
      else res.push(`✋ ${nm(q)}: 최근 1년에서 검증 통과 값 없음(1위 검증 ${nb ? sg(nb.ho.mean) + "R" : "—"}) → 기존 값 유지`); }
    autoLog(`🔧 ${koOf(sym)} 재최적화 끝(${Math.round(r.ms / 1000)}초) — ${res.join(" · ")}`, r.id);
    feed?.(`🔧 ${koOf(sym)} 자동 재최적화 끝: 칸 ${lanesQ.length}개 중 ${ch}개 새 값 적용, ${lanesQ.length - ch}개 기존 값 유지`);
  } catch (e) { autoLog(`❌ ${koOf(sym)} 재최적화 실패: ${e?.message || e}`); for (const q of lanesQ) lane(q.k).since = Date.now(); }
  finally { autoRun = null; save(); }
}
export function setAuto(on) { load(); L.auto.on = !!on; if (!on) { L.auto.q = []; if (autoRun) { import("./optlab.js").then(OL => OL.stop(AUTO_CTX)).catch(() => {}); } } save(); return L.auto.on; }

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
  if (!ln.pos && li > 0 && D.t[li] > ln.lastSig && CB.isEntry(sig, li) && now < D.t[li] + 2 * CB.TF_MS[x.tf] && (L.scope !== "best" || isStar(x)) && !cust()[x.sym]?.off) {
    ln.lastSig = D.t[li];
    const side = sig.fd[li], s = CB.slFrac(D, li, cd.x.k, x.lev);
    if (s == null) { ln.skip++; return; }   // ATR 손절이 이 레버리지의 손절 상한(청산거리 40%)보다 넓음 → 진입 안 함
    const eq = CB.LANE_EQ + ln.pnl, risk = +(eq * CB.RISK).toFixed(2), notional = Math.min(eq * 3, risk / (s + CB.FEE));
    ln.pos = { side, e: px, s, sl: px * (1 - side * s), tp: px * (1 + side * CB.tpFrac(s, cd.x.rr)), be: false, risk, notional: +notional.toFixed(2), margin: +(notional / x.lev).toFixed(2),
      liq: px * (1 - side * 0.95 / x.lev), t: now, t15: Math.floor(now / 900e3) * 900e3, lastBar: D.t[li], bars: 0, round: L.round, cand: L.sel[x.k] ?? 0, rr: cd.x.rr };
    const ev = { t: now, ty: "e", k: x.k, c: x.c, ko: koOf(x.sym), tf: x.tf, lev: x.lev, side, e: px, s, rr: cd.x.rr, sl: ln.pos.sl, tp: ln.pos.tp, owner: L.own[x.c] || "", star: isStar(x), cust: isCustom(x) };
    L.ev.unshift(ev); if (CY) CY.entries.push(ev);
  }
  const Q = ln.pos; if (Q) { Q.px = px; Q.uR = +(((px - Q.e) / Q.e * Q.side - CB.FEE) / (Q.s + CB.FEE)).toFixed(2); Q.roe = +((px - Q.e) / Q.e * Q.side * x.lev * 100).toFixed(1); }   // 지금 손익(R · ROE)
}

// 라운드 끝: 칸마다 후보 9개를 다시 채점 → (1~4라운드) 다음 라운드 값 고르기 · (5라운드) 다섯 번 평균이 가장 좋은 값 = 최종
function rescore(now, feed) {
  const r = L.round, changes = [];
  for (const x of lanesAll()) {
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
    if (best !== cur) { changes.push(x.k); lane(x.k).since = now; }
    L.sel[x.k] = best;
  }
  L.log.unshift({ t: now, round: r, changed: changes.length, text: r >= ROUNDS ? `5라운드 끝 — 칸 ${lanesAll().length}개 최종 커스텀 최적값 확정(다섯 번 평균 1위) · 바뀐 칸 ${changes.length}개` : `${r}라운드 끝 — 후보 다시 채점(앞 4년 학습 점수 + 최근 ${BARS}봉 백테스트 + 이번 라운드 실시간, 건수만큼 가중) · 값이 바뀐 칸 ${changes.length}개` });
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
    const st = comboStat(C.key, r), by = coinsAll().map(([ko, sym]) => { const T = L.trades.filter(t => t.c === C.key && t.sym === sym && t.round === r); return `${ko} ${T.length}건 ${T.reduce((a, t) => a + t.R, 0).toFixed(1)}R`; }).join(" · ");
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
    const now = Date.now(); CY = { entries: [], exits: [] };
    for (const [, sym] of coinsAll()) {
      let B; try { B = await bars(sym); } catch (e) { continue; }
      const c15 = B["15"], px = c15.at(-1)?.c; if (!px) continue;
      for (const tf of CB.TFS) { const M = market(sym, tf, B[tf], now); for (const x of lanesAll()) if (x.sym === sym && x.tf === tf) laneStep(x, M, c15, px, now, feed); }
    }
    // 같은 신호(조합·코인·시간봉·방향)의 30·40·50배 진입/청산은 한 줄로
    const grp = (a, f) => { const m = new Map(); for (const e of a) { const k = f(e); if (!m.has(k)) m.set(k, []); m.get(k).push(e); } return [...m.values()]; };
    for (const g of grp(CY.entries, e => [e.c, e.ko, e.tf, e.side].join("|"))) { const e = g[0];
      feed?.(`🧪 진입 [${shortMd(e.owner)}] ${CB.COMBO_BY[e.c].short} ${e.ko} ${CB.TF_KO[e.tf]} ${g.map(z => z.lev).join("·")}배 ${e.side > 0 ? "롱" : "숏"} @${fmtP(e.e)} · 손절 ${[...new Set(g.map(z => "−" + (z.s * 100).toFixed(2) + "%"))].join("/")} · 익절 1:${e.rr}${g.some(z => z.star) ? " ⭐" : ""}`); }
    for (const g of grp(CY.exits, e => [e.c, e.ko, e.tf, e.why].join("|"))) { const e = g[0];
      feed?.(`🧪 청산 ${CB.COMBO_BY[e.c].short} ${e.ko} ${CB.TF_KO[e.tf]} ${g.map(z => z.lev).join("·")}배 ${e.side > 0 ? "롱" : "숏"} ${e.why} ${g.map(z => sg(z.R) + "R").join("/")}`); }
    CY = null;
    for (const [s, u] of Object.entries(cust())) if (u.off && !lanesAll().some(x => x.sym === s && L.lanes[x.k]?.pos)) { delete CUST[s]; try { saveCust(); } catch (e) {} }   // 해제한 추가 코인: 보유분이 다 끝나면 칸 삭제
    autoStep(feed).catch(() => {});   // 🔧 손실 자동 재최적화(대기 중인 칸이 있으면 백그라운드로 1코인씩)
    if (L.round <= ROUNDS && now >= L.roundAt + L.roundH * 3600e3) { const r = L.round; rescore(now, feed); save(); reviewRound(r, feed, tg).catch(() => {}); }
  } finally { busy = false; CY = null; save(); }
}

export function setScope(sc) { load(); L.scope = sc === "best" ? "best" : "all"; save(); return L.scope; }   // 대표만: 다른 칸은 새 진입만 멈춤(보유분은 끝까지 관리)
export function setOn(on) { load(); L.on = !!on; save(); return L.on; }
export function setRoundH(h) { load(); L.roundH = Math.max(1, Math.min(168, +h || 24)); save(); return L.roundH; }
export function restartRounds() { load(); L.round = 1; L.roundAt = Date.now(); L.hist = {}; L.final = null; L.sel = {}; L.log.unshift({ t: Date.now(), round: 0, text: "라운드 처음부터(값은 후보 1위로 되돌림 · 거래 기록은 유지)" }); save(); }

// 🔬 직접 최적화 결과 적용 / 해제 (optlab.js)
export function applyCustom(r) {
  load(); const sym = r?.sym; if (!sym || !r.out) throw new Error("적용할 결과가 없습니다");
  const prev = cust()[sym];
  CUST[sym] = { id: r.id, sym, ko: r.ko, start: r.start, end: r.end, made: r.made, span: r.span, tfs: r.tfs, levs: r.levs, combos: r.combos, out: r.out, best: r.best, at: Date.now() };
  try { saveCust(); } catch (e) { if (prev) CUST[sym] = prev; else delete CUST[sym]; throw new Error("저장 공간이 부족합니다 — 다른 코인의 직접 최적화 적용을 해제한 뒤 다시 하세요"); }
  let n = 0; for (const x of lanesAll()) if (x.sym === sym) { delete L.sel[x.k]; delete L.hist[x.k]; if (isCustom(x)) { n++; lane(x.k).since = Date.now(); } }
  L.log.unshift({ t: Date.now(), round: L.round, text: `🔬 ${r.ko} 직접 최적화 값 적용(${day(r.start)}~${day(r.end)} · 칸 ${n}개)${BASE.has(sym) ? "" : " — 새 코인 칸 추가"}` });
  save(); return { lanes: n };
}
export function removeCustom(sym) {
  load(); const u = cust()[sym]; if (!u) return false;
  const mine = lanesAll().filter(x => x.sym === sym), open = mine.some(x => L.lanes[x.k]?.pos);
  if (!BASE.has(sym) && open) u.off = true; else delete CUST[sym];
  try { saveCust(); } catch (e) {}
  for (const x of mine) { delete L.sel[x.k]; delete L.hist[x.k]; }
  L.log.unshift({ t: Date.now(), round: L.round, text: `🔬 ${u.ko} 직접 최적화 값 해제${BASE.has(sym) ? " → 기본 5년 값으로" : open ? " — 보유 포지션이 끝나면 칸 삭제" : " — 칸 삭제"}` });
  save(); return true;
}
export const customList = () => Object.values(cust()).map(u => ({ sym: u.sym, ko: u.ko, start: u.start, end: u.end, made: u.made, id: u.id, tfs: u.tfs, levs: u.levs, spanD: Math.round((u.span || 365.25 * 864e5) / 864e5), off: !!u.off, extra: !BASE.has(u.sym), auto: !!u.auto, nAuto: Object.keys(u.meta || {}).length }));
export function resetLab() { const own = L?.own; L = blank(); if (own) L.own = own; save(); }

// 화면·뉴트론용 요약
const spanL = x => { if (!isCustom(x)) return 365; const u = cust()[x.sym]; return Math.round((u.meta?.[x.tf + "|" + x.c + "|" + x.lev]?.span || u.span || 365.25 * 864e5) / 864e5); };   // 구간 길이(일) — 기본 5년 값은 1년
export function labState() {
  load(); const now = Date.now(), open = [];
  const combos = CB.COMBOS.map(C => { const st = comboStat(C.key); let pass = 0, luck = 0, tot = 0, op = 0;
    for (const x of lanesAll()) if (x.c === C.key) { const cd = candOf(x); tot++; if (cd?.pass) pass++; if (cd?.pass && !cd.luck) luck++; const P = L.lanes[x.k]?.pos; if (P) { op++; open.push({ ...x, star: isStar(x), cust: isCustom(x), ko: koOf(x.sym), cshort: C.short, side: P.side, e: P.e, px: P.px ?? P.e, sl: P.sl, tp: P.tp, be: P.be, t: P.t, owner: L.own[C.key], uR: P.uR ?? 0, roe: P.roe ?? 0, upnl: +((P.uR ?? 0) * P.risk).toFixed(2), s: P.s, rr: P.rr ?? null, margin: P.margin, liq: P.liq }); } }
    return { key: C.key, ko: C.ko, short: C.short, owner: L.own[C.key] || "", ownerShort: shortMd(L.own[C.key]), ...st, open: op, pass, passReal: luck, lanes: tot, cur: comboStat(C.key, L.round), reviews: (L.reviews[C.key] || []).slice(0, 2) }; });
  const grid = {};
  for (const x of lanesAll()) { const cd = candOf(x), ln = L.lanes[x.k] || {};
    ((grid[x.c] ||= {})[x.sym] ||= {})[x.tf + "|" + x.lev] = cd ? { star: isStar(x), cust: isCustom(x), auto: !!cust()[x.sym]?.meta?.[x.tf + "|" + x.c + "|" + x.lev], spanD: spanL(x), p: CB.paramText(x.c, cd.p), x: CB.exitText(cd.x), pass: cd.pass, luck: cd.luck, ho: cd.ho, tr: cd.tr, lb: cd.lb, sel: L.sel[x.k] ?? 0, nC: cands(x.c, x.sym, x.tf, x.lev).length, n: ln.n || 0, R: ln.R || 0, pnl: ln.pnl || 0, skip: ln.skip || 0, pos: ln.pos ? { side: ln.pos.side, be: ln.pos.be, uR: ln.pos.uR ?? null } : null } : null; }
  // ⭐ 코인 × 30·40·50배 대표 칸(지금 라운드에서 쓰는 값 + 실시간 성적)
  const best = [], bs = { n: 0, R: 0, pnl: 0, open: 0 };
  for (const [ko, sym] of coinsAll()) for (const lev of [30, 40, 50]) { const b = bestOf(sym, lev); if (!b) continue;
    const x = lanesAll().find(z => z.c === b.c && z.sym === sym && z.tf === b.tf && z.lev === lev), cd = x && candOf(x), ln = (x && L.lanes[x.k]) || {}; if (!cd) continue;
    bs.n += ln.n || 0; bs.R += ln.R || 0; bs.pnl += ln.pnl || 0; if (ln.pos) bs.open++;
    best.push({ ko, sym, lev, c: b.c, cko: CB.COMBO_BY[b.c].ko, cshort: CB.COMBO_BY[b.c].short, tf: b.tf, p: CB.paramText(b.c, cd.p), x: CB.exitText(cd.x), cap: +(40 / lev).toFixed(2),
      tr: cd.tr, ho: cd.ho, lb: cd.lb, pass: cd.pass, luck: b.luck || cd.luck, of: b.of, cust: isCustom(x), spanD: spanL(x), n: ln.n || 0, R: ln.R || 0, pnl: ln.pnl || 0, pos: ln.pos ? { side: ln.pos.side } : null }); }
  return { on: L.on, scope: L.scope, best, bestSum: { ...bs, R: +bs.R.toFixed(2), pnl: +bs.pnl.toFixed(2) }, round: Math.min(L.round, ROUNDS), rounds: ROUNDS, done: !!L.final, roundH: L.roundH, left: Math.max(0, L.roundAt + L.roundH * 3600e3 - now), made: META.made, from: META.from,
    combos, grid, open, trades: L.trades.slice(0, 40), log: L.log.slice(0, 8), tfs: CB.TFS, levs: CB.LEVS, tfKo: CB.TF_KO, coins: coinsAll(), lanes: lanesAll().length, custom: customList(),
    events: (L.ev || []).slice(0, 40), auto: { on: !!L.auto?.on, q: (L.auto?.q || []).map(q => ({ ko: koOf(q.sym), tf: q.tf, lev: q.lev, c: q.c, why: q.why })), run: autoRun, log: (L.auto?.log || []).slice(0, 8), nDay: L.auto?.nDay || 0, rule: AUTO } };
}
