// 🧘 관망 규칙집 — "언제 쉬는가"를 AI·코드가 스스로 고치되, 고친 것은 실제 데이터로 검증해 좋아질 때만 남긴다.
//   개념 출처(코드 복사 없음): chrisworsey55/atlas-gic(ATLAS: 한 번에 하나만 고치고 성과로 유지/되돌림 · git 이력),
//   The-R4V3N/Nexus(규칙집 자기 재작성), mcqx4/ffrdm·Ganador1/FenixAI(연속 손실 휴식·감정 상태), DeepSeek 정리 문서의 관망 조건 목록.
//   순수 함수만(브라우저/노드 공용) — 노드에서 실데이터로 그대로 시험할 수 있다.
//
// 2026-10-06 실측(바이낸스 선물 1시간봉 1년 · 6코인 · 매매법 전부 · 수수료 포함, 데스크처럼 코인당 1포지션·동시 4개):
//   기본 −0.035R → 4H 역행 금지 −0.023 · EMA 배열 필수 +0.003 · 연속 3손실 뒤 24시간 휴식 +0.059 · 셋 함께 쓸 때 전·후반 모두 플러스.
//   ADX<20 · 거래량<0.5배 · RSI 40~60 · 공포탐욕 극단 · 펀딩 과열은 막아도 좋아지지 않았다(기본 꺼짐, 데이터가 바뀌면 진화가 켤 수 있음).
//   '연속 이익 뒤 비중 축소(과신 방지)'는 오히려 손해였다(연속 3이익 뒤 거래 평균 +0.23R) → 규칙으로 넣지 않음.

export const RULES = [
  { id: "htf",    label: "상위 시간봉 추세 역행이면 관망(1시간봉은 4시간)", on: true,  p: null, test: x => x.htf === -x.side },
  { id: "align",  label: "EMA 9·20·50 배열이 방향과 다르면 관망", on: true,  p: null, test: x => x.al === false },
  { id: "streak", label: "연속 손실 뒤 휴식",                   on: true,  p: { L: 3, h: 24 }, steps: { L: [2, 3, 4, 5], h: [6, 12, 24, 36] }, desk: true },
  { id: "adx",    label: "ADX가 낮으면(추세 없음) 관망",         on: false, p: 20,  steps: [15, 18, 20, 23, 25], test: (x, p) => x.adx != null && x.adx < p },
  { id: "vol",    label: "거래량이 평균보다 적으면 관망",         on: false, p: 0.5, steps: [0.4, 0.5, 0.6, 0.7, 0.8], test: (x, p) => x.vr != null && x.vr < p },
  { id: "rsiN",   label: "RSI 중립 구간(50±p)이면 관망",         on: false, p: 10,  steps: [5, 8, 10, 12], test: (x, p) => x.rsi != null && Math.abs(x.rsi - 50) < p },
  { id: "rsiX",   label: "롱은 RSI 과매수·숏은 과매도면 자제",     on: false, p: 70,  steps: [65, 70, 75, 80], test: (x, p) => x.rsi != null && (x.side > 0 ? x.rsi > p : x.rsi < 100 - p) },
  { id: "fng",    label: "공포탐욕 극단 반대쪽 진입 금지",         on: false, p: 20,  steps: [15, 20, 25], test: (x, p) => x.fng != null && (x.side > 0 ? x.fng > 100 - p : x.fng < p) },
  // 2026-10-06 실측: 1시간봉 매매에 '15분 추세 같은 방향'은 단독으로 −0.046 → −0.016R(전·후반 개선)이지만, 위 EMA 배열 규칙과 겹쳐 규칙집 위에서는 차이 없음 → 기본 꺼짐(진화가 켤 수 있음)
  { id: "ltf",    label: "하위 시간봉 추세가 반대면 관망(1시간봉은 15분·15분봉은 5분)", on: false, p: null, test: x => x.ltf != null && x.ltf === -x.side },
  // 15분봉 매매: 1시간·4시간 추세가 모두 같은 방향일 때만 −0.123 → −0.084R(전·후반 개선, 여전히 마이너스라 실전 투입은 워크포워드 관문이 결정)
  { id: "scalp",  label: "스캘핑(5·15분 신호)은 1시간·4시간 추세가 모두 같은 방향일 때만", on: true, p: null, test: x => x.small === true && !(x.htf === x.side && x.up2 === x.side) },
];
export const RULE_BY = Object.fromEntries(RULES.map(r => [r.id, r]));
export function defaultBook() { return { ver: 1, rules: Object.fromEntries(RULES.map(r => [r.id, { on: r.on, p: r.p && typeof r.p === "object" ? { ...r.p } : r.p }])), log: [] }; }
export function normBook(b) {   // 저장본에 새 규칙이 없으면 기본값으로 채운다
  const d = defaultBook(); if (!b || !b.rules) return d;
  for (const r of RULES) if (!b.rules[r.id]) b.rules[r.id] = d.rules[r.id];
  b.log ||= []; b.ver ||= 1; return b;
}
export const ruleText = (id, p) => { const r = RULE_BY[id]; if (!r) return id;
  if (id === "streak") return `${p.L}연속 손실 뒤 ${p.h}시간 휴식`; if (id === "adx") return `ADX<${p} 관망`; if (id === "vol") return `거래량<${p}×평균 관망`;
  if (id === "rsiN") return `RSI ${50 - p}~${50 + p} 관망`; if (id === "rsiX") return `롱 RSI>${p}·숏 RSI<${100 - p} 자제`; if (id === "fng") return `공포탐욕 <${p}에 숏·>${100 - p}에 롱 금지`; return r.label; };

const fin = v => v != null && Number.isFinite(v);
/** 신호 봉 i 의 맥락. H = 상위 시간봉(prepareHTF), tClose = 신호 봉 마감 시각, ENG = strategies.js */
export function ctxAt(ENG, I, i, H, side, tClose, extra = {}) {
  const hb = H ? ENG.htfBiasAt(H, tClose) : { bias: 0 };
  const e9 = I.ema9[i], e20 = I.ema20[i], e50 = I.ema50[i];
  const al = fin(e9) && fin(e20) && fin(e50) ? (side > 0 ? e9 > e20 && e20 > e50 : e9 < e20 && e20 < e50) : null;
  return { side, htf: hb.bias, al, adx: fin(I.adx[i]) ? I.adx[i] : null, vr: fin(I.volMa[i]) && I.volMa[i] > 0 ? I.v[i] / I.volMa[i] : null, rsi: fin(I.rsi[i]) ? I.rsi[i] : null, ...extra };
}
/** 개별 신호 점검(연속 손실 휴식 제외). 막는 규칙이 있으면 {block:id, why} */
export function check(book, x) {
  for (const r of RULES) { const st = book.rules[r.id]; if (!st?.on || r.desk) continue; if (r.test(x, st.p)) return { block: r.id, why: ruleText(r.id, st.p) }; }
  return null;
}
/** 연속 손실 휴식 상태: closed = 시간순 청산 거래 [{R, t1}] */
export function restUntil(book, closed) {
  const st = book.rules.streak; if (!st?.on || !closed.length) return 0;
  let n = 0; for (let j = closed.length - 1; j >= 0 && closed[j].R < 0; j--) n++;
  return n >= st.p.L ? closed.at(-1).t1 + st.p.h * 3600e3 : 0;
}

// ── 검증: 데스크처럼 다시 돌려 본다(코인당 1포지션 · 동시 maxPos · 시간순) ──
// trades: [{s(코인), t(진입), t1(청산), R, ...ctx}]
export function replay(trades, book, maxPos = 4) {
  const T = [...trades].sort((a, b) => a.t - b.t), open = [], closed = [], taken = []; let rest = 0;
  for (const x of T) {
    let changed = false;
    for (let k = open.length - 1; k >= 0; k--) if (open[k].t1 <= x.t) { closed.push(open[k]); open.splice(k, 1); changed = true; }
    if (changed) { closed.sort((a, b) => a.t1 - b.t1); rest = Math.max(rest, restUntil(book, closed)); }
    if (open.length >= maxPos || open.some(o => o.s === x.s)) continue;
    if (x.t < rest || check(book, x)) continue;
    open.push(x); taken.push(x);
  }
  return taken;
}
const stat = a => { const n = a.length, s = a.reduce((x, t) => x + t.R, 0), m = n ? s / n : 0, sd = n > 1 ? Math.sqrt(a.reduce((x, t) => x + (t.R - m) ** 2, 0) / (n - 1)) : 0;
  return { n, mean: +m.toFixed(3), sum: +s.toFixed(1), wr: n ? Math.round(a.filter(t => t.R > 0).length / n * 100) : 0, se: n ? +(sd / Math.sqrt(n)).toFixed(3) : 0 }; };
/** 규칙집 성적: 전체 + 전반/후반(시간 반으로) */
export function score(trades, book, maxPos = 4) {
  if (!trades.length) return null;
  const ts = trades.map(t => t.t).sort((a, b) => a - b), mid = ts[Math.floor(ts.length / 2)];
  const a = replay(trades, book, maxPos);
  return { all: stat(a), h1: stat(a.filter(t => t.t < mid)), h2: stat(a.filter(t => t.t >= mid)) };
}
/** 수정 하나 적용(복사본). edit = {id, on?, p?} */
export function applyEdit(book, e) {
  const b = JSON.parse(JSON.stringify(book)), r = RULE_BY[e?.id]; if (!r) return null;
  const st = b.rules[e.id];
  if (e.on != null) st.on = !!e.on;
  if (e.p != null) {
    if (e.id === "streak") { const L = Math.round(+e.p.L), h = Math.round(+e.p.h); if (!(L >= 2 && L <= 5 && h >= 0 && h <= 48)) return null; st.p = { L, h }; }
    else { const v = +e.p, lo = Math.min(...r.steps), hi = Math.max(...r.steps); if (!Number.isFinite(v) || v < lo || v > hi) return null; st.p = v; }
  }
  return b;
}
/** 관문: 새 규칙집이 평균 R 의 표준오차(1SE, 최소 0.02R) 이상 좋아지고, 전반·후반 둘 다 나빠지지 않고, 거래가 충분할 때만 채택.
 *  (2개월 창의 거래 100여 건은 잡음이 커서, 1SE 미만의 개선은 우연과 구분되지 않는다 — 규칙이 매 점검마다 흔들리는 것 방지) */
export function gate(base, cand, minN = 60) {
  if (!base || !cand) return { ok: false, why: "데이터 없음" };
  if (cand.all.n < minN) return { ok: false, why: `거래 ${cand.all.n}건 < ${minN}` };
  const d = +(cand.all.mean - base.all.mean).toFixed(3);
  const need = Math.max(0.02, cand.all.se || 0);
  if (d < need) return { ok: false, why: `평균 ${base.all.mean}→${cand.all.mean}R (개선 ${d} < 필요 ${need.toFixed(3)})`, d };
  if (cand.h1.mean < base.h1.mean - 0.005 || cand.h2.mean < base.h2.mean - 0.005) return { ok: false, why: `전반 ${base.h1.mean}→${cand.h1.mean} · 후반 ${base.h2.mean}→${cand.h2.mean} (한쪽이 나빠짐)`, d };
  return { ok: true, why: `평균 ${base.all.mean}→${cand.all.mean}R · 전반 ${base.h1.mean}→${cand.h1.mean} · 후반 ${base.h2.mean}→${cand.h2.mean}`, d };
}
/** 코드가 스스로 찾는 한 걸음 수정 후보(켜기/끄기 · 값 한 칸) */
export function neighbors(book) {
  const out = [];
  for (const r of RULES) { const st = book.rules[r.id];
    out.push({ id: r.id, on: !st.on });
    if (!st.on) continue;
    if (r.id === "streak") { for (const L of r.steps.L) if (L !== st.p.L) out.push({ id: r.id, p: { L, h: st.p.h } }); for (const h of r.steps.h) if (h !== st.p.h) out.push({ id: r.id, p: { L: st.p.L, h } }); }
    else if (r.steps) for (const v of r.steps) if (v !== st.p) out.push({ id: r.id, p: v });
  }
  return out;
}
/** 한 세대: AI 제안(있으면 먼저) → 코드 이웃 탐색. 통과하는 것 중 가장 좋은 '하나'만 채택(ATLAS: 한 번에 하나) */
export function evolve(trades, book, { proposal = null, maxPos = 4, minN = 60 } = {}) {
  const base = score(trades, book, maxPos); if (!base) return { base: null, tried: [], adopted: null };
  const tried = [];
  const test = (e, src) => { const b2 = applyEdit(book, e); if (!b2) { tried.push({ e, src, ok: false, why: "범위 밖" }); return null; } const sc = score(trades, b2, maxPos), g = gate(base, sc, minN); const row = { e, src, ok: g.ok, why: g.why, d: g.d ?? null, sc, book: b2 }; tried.push(row); return row; };
  let best = null;
  if (proposal) { const r = test(proposal, "AI"); if (r?.ok) best = r; }
  if (!best) for (const e of neighbors(book)) { const r = test(e, "코드"); if (r?.ok && (!best || r.d > best.d)) best = r; }
  return { base, tried: tried.map(({ book, ...x }) => x), adopted: best };
}
export const editText = e => { const r = RULE_BY[e?.id]; if (!r) return "?"; if (e.on === false) return `'${r.label}' 끄기`; if (e.on === true && e.p == null) return `'${r.label}' 켜기`; return `${ruleText(e.id, e.p)}${e.on ? " (켜기)" : ""}`; };
